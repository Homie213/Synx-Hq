#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use include_dir::{include_dir, Dir};
use std::borrow::Cow;
use tao::{
    event::{Event, WindowEvent},
    event_loop::{ControlFlow, EventLoop},
    window::WindowBuilder,
};
use wry::WebViewBuilder;

static ASSETS: Dir = include_dir!("$CARGO_MANIFEST_DIR/dist");

fn main() -> wry::Result<()> {
    // Persist login session, tokens & local storage in %LOCALAPPDATA%
    if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
        let data_dir = std::path::PathBuf::from(local_app_data).join("SasyndevCONTROL");
        let _ = std::fs::create_dir_all(&data_dir);
        unsafe {
            std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", &data_dir);
        }
    }

    let event_loop = EventLoop::new();
    let window = WindowBuilder::new()
        .with_title("Sasyndev CONTROL")
        .with_inner_size(tao::dpi::LogicalSize::new(1280.0, 800.0))
        .build(&event_loop)
        .expect("Failed to create window");

    let builder = WebViewBuilder::new()
        .with_devtools(true)
        .with_initialization_script("window.__SASYNDEV_DESKTOP__ = true;")
        .with_custom_protocol("app".into(), move |_webview_id, request| {
            let path = request.uri().path().trim_start_matches('/');
            let file_path = if path.is_empty() { "index.html" } else { path };

            if let Some(file) = ASSETS.get_file(file_path) {
                let mime = mime_guess::from_path(file_path)
                    .first_or_octet_stream()
                    .to_string();
                wry::http::Response::builder()
                    .header(wry::http::header::CONTENT_TYPE, mime)
                    .header(wry::http::header::ACCESS_CONTROL_ALLOW_ORIGIN, "*")
                    .status(200)
                    .body(Cow::Borrowed(file.contents()))
                    .unwrap()
            } else if let Some(index_file) = ASSETS.get_file("index.html") {
                // SPA fallback for React Router navigation
                wry::http::Response::builder()
                    .header(wry::http::header::CONTENT_TYPE, "text/html; charset=utf-8")
                    .header(wry::http::header::ACCESS_CONTROL_ALLOW_ORIGIN, "*")
                    .status(200)
                    .body(Cow::Borrowed(index_file.contents()))
                    .unwrap()
            } else {
                wry::http::Response::builder()
                    .status(404)
                    .body(Cow::Borrowed(b"404 Not Found" as &[u8]))
                    .unwrap()
            }
        })
        .with_url("http://app.localhost/");

    let _webview = builder.build(&window)?;

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;

        if let Event::WindowEvent {
            event: WindowEvent::CloseRequested,
            ..
        } = event
        {
            *control_flow = ControlFlow::Exit;
        }
    });
}
