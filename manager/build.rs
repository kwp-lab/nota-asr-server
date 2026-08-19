fn main() {
    println!("cargo:rerun-if-changed=assets/manager-icon.ico");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        winresource::WindowsResource::new()
            .set_icon("assets/manager-icon.ico")
            .compile()
            .expect("failed to embed Nota ASR Manager Windows resources");
    }
}
