fn main() {
    println!("cargo:rerun-if-changed=dist");
    println!("cargo:rerun-if-changed=src/main.rs");
    if std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default() == "windows" {
        let mut res = winres::WindowsResource::new();
        res.set_icon("app_icon.ico");
        let _ = res.compile();
    }
}
