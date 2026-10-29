import subprocess

from src.media import ffmpeg


def test_final_args_use_nvenc_when_the_gpu_can_encode(monkeypatch):
    monkeypatch.setattr(ffmpeg, "nvenc_available", lambda: True)
    args = ffmpeg.build_final_video_encode_args()
    assert args[:2] == ["-c:v", "h264_nvenc"] and "-cq" in args and "-r" in args
    monkeypatch.setattr(ffmpeg, "nvenc_available", lambda: False)
    assert ffmpeg.build_final_video_encode_args()[:2] == ["-c:v", "libx264"]


def test_cpu_fallback_swaps_only_the_video_encoder(monkeypatch):
    monkeypatch.setattr(ffmpeg, "nvenc_available", lambda: True)
    command = ["ffmpeg", "-y", "-i", "in.mp4", *ffmpeg.build_final_video_encode_args(), "-c:a", "aac", "out.mp4"]

    fallback = ffmpeg.cpu_encode_fallback(command)

    assert "h264_nvenc" not in fallback and "-cq" not in fallback
    assert fallback[4:10] == ["-c:v", "libx264", "-preset", "medium", "-crf", "19"]
    assert fallback[:4] == command[:4] and fallback[-3:] == ["-c:a", "aac", "out.mp4"]
    intermediate = ["ffmpeg", *ffmpeg.intermediate_video_encode_args(), "o.mp4"]
    assert ffmpeg.cpu_encode_fallback(intermediate)[1:7] == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16"]


def test_failed_gpu_encode_is_rendered_on_the_cpu(monkeypatch, tmp_path):
    # This machine has no NVIDIA GPU, so forcing NVENC makes the real ffmpeg fail
    # and the clip must still come out via libx264.
    monkeypatch.setattr(ffmpeg, "nvenc_available", lambda: True)
    source = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=3", "-f", "lavfi",
                    "-i", "sine=d=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)], check=True)
    out = tmp_path / "cut.mp4"

    assert ffmpeg.render_source_ranges_ffmpeg(source, [(0.5, 2.5)], out)
    assert 1.8 < ffmpeg.ffprobe_duration(out) < 2.3
