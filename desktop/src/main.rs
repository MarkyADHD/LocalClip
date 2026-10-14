// LocalClip desktop app: a window around the same launcher the LocalClip shortcut runs.
// Opening it starts LocalClip.ps1 hidden and shows the app once it's up; closing the window runs
// Close LocalClip.ps1. It also shows a banner when a newer GitHub release is out.
#![windows_subsystem = "windows"]

use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};
use std::{env, fs};
use tao::dpi::LogicalSize;
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::platform::windows::IconExtWindows;
use tao::window::{Icon, WindowBuilder};
use wry::{NewWindowResponse, WebContext, WebViewBuilder};

const APP_URL: &str = "http://localhost:3107";
const REPO: &str = "MarkyADHD/LocalClip";
const NO_WINDOW: u32 = 0x0800_0000; // CREATE_NO_WINDOW
static LAUNCHER_PID: AtomicU32 = AtomicU32::new(0);

enum Msg {
    Ready,
    Failed(String),
    Update,
}

fn main() {
    let exe = env::current_exe().unwrap();
    let Some(dir) = find_install(&exe) else {
        // Not installed yet: run the normal installer in a visible window. It installs this app too.
        let cmd = format!("irm https://raw.githubusercontent.com/{REPO}/main/install.ps1 | iex");
        let _ = Command::new("cmd")
            .args(["/c", "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &cmd, "||", "pause"])
            .spawn();
        return;
    };

    let event_loop = EventLoopBuilder::<Msg>::with_user_event().build();
    let window = WindowBuilder::new()
        .with_title("LocalClip")
        .with_window_icon(Icon::from_resource(1, None).ok())
        .with_inner_size(LogicalSize::new(1360.0, 880.0))
        .build(&event_loop)
        .unwrap();

    let mut context = WebContext::new(Some(dir.join(".localclip").join("webview")));
    let proxy = event_loop.create_proxy();
    let webview = WebViewBuilder::new_with_web_context(&mut context)
        .with_html(LOADING_PAGE)
        .with_initialization_script(update_banner_script())
        .with_ipc_handler(move |req| {
            if req.body() == "update" {
                let _ = proxy.send_event(Msg::Update);
            }
        })
        // Links to other sites open in the normal browser instead of replacing the app.
        .with_navigation_handler(|url| {
            let local = url.starts_with(APP_URL) || url.starts_with("http://127.0.0.1");
            if !local && url.starts_with("http") {
                open_in_browser(&url);
            }
            local || !url.starts_with("http")
        })
        .with_new_window_req_handler(|url, _| {
            open_in_browser(&url);
            NewWindowResponse::Deny
        })
        .build(&window)
        .unwrap();

    let proxy = event_loop.create_proxy();
    let launch_dir = dir.clone();
    std::thread::spawn(move || {
        let _ = proxy.send_event(launch(&launch_dir));
    });

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(Msg::Ready) => {
                let _ = webview.load_url(APP_URL);
            }
            Event::UserEvent(Msg::Failed(log)) => {
                // ponytail: Rust's {:?} string escaping happens to be a valid JS string literal.
                let _ = webview.evaluate_script(&format!("showError({log:?})"));
            }
            Event::UserEvent(Msg::Update) => {
                start_updater(&exe);
                shut_down(&window, &dir, control_flow);
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => shut_down(&window, &dir, control_flow),
            _ => {}
        }
    });
}

// The folder with LocalClip.ps1: next to this exe, or the installer's %LOCALAPPDATA%\LocalClip.
fn find_install(exe: &Path) -> Option<PathBuf> {
    let beside = exe.parent().map(Path::to_path_buf);
    let default = env::var_os("LOCALAPPDATA").map(|d| PathBuf::from(d).join("LocalClip"));
    [beside, default].into_iter().flatten().find(|d| d.join("LocalClip.ps1").exists())
}

fn powershell(dir: &Path, script: &str) -> Command {
    let mut cmd = Command::new("powershell");
    cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
        .arg(dir.join(script))
        .current_dir(dir)
        .creation_flags(NO_WINDOW);
    cmd
}

// Runs the usual launcher (installs, updates, starts everything) and waits until the app is up.
fn launch(dir: &Path) -> Msg {
    let logs = dir.join(".localclip").join("logs");
    let _ = fs::create_dir_all(&logs);
    let log = logs.join("launcher.log");
    let Ok(out) = fs::File::create(&log) else { return Msg::Failed(format!("Can't write {}", log.display())) };
    let child = powershell(dir, "LocalClip.ps1")
        .arg("-NoBrowser")
        .stdout(out.try_clone().unwrap())
        .stderr(out)
        .spawn();
    let Ok(mut child) = child else { return Msg::Failed("Couldn't start PowerShell.".into()) };
    LAUNCHER_PID.store(child.id(), Ordering::SeqCst);
    let ok = child.wait().is_ok_and(|s| s.success());
    LAUNCHER_PID.store(0, Ordering::SeqCst);
    if ok {
        return Msg::Ready;
    }
    let text = fs::read_to_string(&log).unwrap_or_default();
    let tail: Vec<&str> = text.lines().rev().take(25).collect();
    let tail: Vec<&str> = tail.into_iter().rev().collect();
    Msg::Failed(format!("{}\n\nFull log: {}", tail.join("\n"), log.display()))
}

// Same as the Close LocalClip shortcut, plus stopping a launcher that's still starting up.
fn shut_down(window: &tao::window::Window, dir: &Path, control_flow: &mut ControlFlow) {
    window.set_visible(false);
    let pid = LAUNCHER_PID.load(Ordering::SeqCst);
    if pid != 0 {
        let _ = Command::new("taskkill").args(["/PID", &pid.to_string(), "/T", "/F"]).creation_flags(NO_WINDOW).status();
    }
    let _ = powershell(dir, "Close LocalClip.ps1").status();
    *control_flow = ControlFlow::Exit;
}

// Downloads the latest LocalClip.exe over this one once this process has exited, then reopens it.
fn start_updater(exe: &Path) {
    let exe = exe.display().to_string().replace('\'', "''");
    let script = format!(
        "$ProgressPreference='SilentlyContinue'; $exe='{exe}'; \
         try {{ Invoke-WebRequest https://github.com/{REPO}/releases/latest/download/LocalClip.exe -OutFile \"$exe.new\" -UseBasicParsing; \
         Wait-Process -Id {pid} -ErrorAction SilentlyContinue; Move-Item -Force \"$exe.new\" $exe }} \
         catch {{ Wait-Process -Id {pid} -ErrorAction SilentlyContinue }}; Start-Process $exe",
        pid = std::process::id()
    );
    let _ = Command::new("powershell")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script])
        .creation_flags(NO_WINDOW)
        .spawn();
}

fn open_in_browser(url: &str) {
    let _ = Command::new("explorer").arg(url).spawn();
}

fn update_banner_script() -> String {
    UPDATE_BANNER.replace("__VERSION__", env!("CARGO_PKG_VERSION")).replace("__REPO__", REPO)
}

const UPDATE_BANNER: &str = r#"
if (window.top === window && location.origin === "http://localhost:3107" && !sessionStorage.getItem("lc-update-seen")) {
  sessionStorage.setItem("lc-update-seen", "1");
  const parts = v => v.replace(/^v/, "").split(".").map(Number);
  const newer = (a, b) => { const x = parts(a), y = parts(b); for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
  fetch("https://api.github.com/repos/__REPO__/releases/latest").then(r => r.ok ? r.json() : null).then(rel => {
    if (!rel || !newer(rel.tag_name, "__VERSION__")) return;
    const bar = document.createElement("div");
    bar.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;display:flex;gap:10px;align-items:center;padding:12px 14px;border-radius:10px;background:#18181b;color:#fafafa;font:14px system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.35)";
    bar.innerHTML = '<span>LocalClip ' + rel.tag_name + ' is available.</span>' +
      '<a href="' + rel.html_url + '" target="_blank" style="color:#a1a1aa">What\'s new</a>' +
      '<button style="background:#fafafa;color:#18181b;border:0;border-radius:6px;padding:6px 10px;cursor:pointer;font:inherit">Update and restart</button>' +
      '<button aria-label="Later" style="background:none;color:#a1a1aa;border:0;cursor:pointer;font:inherit">Later</button>';
    const [update, later] = bar.querySelectorAll("button");
    update.onclick = () => { update.textContent = "Updating..."; window.ipc.postMessage("update"); };
    later.onclick = () => bar.remove();
    document.body.appendChild(bar);
  }).catch(() => {});
}
"#;

const LOADING_PAGE: &str = r#"<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin: 0; height: 100vh; display: grid; place-items: center; background: #09090b; color: #fafafa; font: 15px system-ui, sans-serif; }
  .box { max-width: 760px; padding: 24px; text-align: center; }
  .spin { width: 34px; height: 34px; margin: 0 auto 18px; border: 3px solid #3f3f46; border-top-color: #fafafa; border-radius: 50%; animation: s 1s linear infinite; }
  @keyframes s { to { transform: rotate(360deg) } }
  p { color: #a1a1aa; }
  pre { text-align: left; white-space: pre-wrap; background: #18181b; padding: 14px; border-radius: 8px; color: #fca5a5; font-size: 12px; max-height: 60vh; overflow: auto; }
</style></head><body><div class="box" id="box">
  <div class="spin"></div>
  <h2>Starting LocalClip...</h2>
  <p>This takes a few seconds. The first start, or the first start after an update, downloads and builds everything and can take a while.</p>
</div><script>
  function showError(log) {
    document.getElementById("box").innerHTML = "<h2>LocalClip didn't start</h2><p>Close this window and open LocalClip again. If it keeps happening, this is what went wrong:</p><pre></pre>";
    document.querySelector("pre").textContent = log;
  }
</script></body></html>"#;
