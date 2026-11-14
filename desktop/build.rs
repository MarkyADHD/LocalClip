fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let mut res = winresource::WindowsResource::new();
        res.set_icon_with_id("../assets/localclip.ico", "1");
        // The code signing service only signs files whose product name is the project's name.
        res.set("ProductName", "LocalClip");
        res.set("FileDescription", "LocalClip");
        res.compile().unwrap();
    }
}
