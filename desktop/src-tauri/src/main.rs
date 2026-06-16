// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

struct AppState {
    /// Handle to the Python backend child process.
    backend: Mutex<Option<Child>>,
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Try to find the Python backend script relative to the app bundle.
            let backend_path = find_backend_script(app);
            if let Some(path) = backend_path {
                let child = start_python_backend(&path);
                if let Ok(c) = child {
                    app.manage(AppState {
                        backend: Mutex::new(Some(c)),
                    });
                }
            }
            Ok(())
        })
        .on_window_event(|app, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Cleanly terminate the Python backend when the window closes.
                if let Some(state) = app.try_state::<AppState>() {
                    let mut lock = state.backend.lock().unwrap();
                    if let Some(mut child) = lock.take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Discover the Python backend script path.
///
/// In development the script is at `../src/instr_core/api_server.py`
/// relative to the `src-tauri` directory.
/// In a production bundle it may be bundled alongside the binary or
/// shipped as a sidecar.
fn find_backend_script(app: &tauri::App) -> Option<std::path::PathBuf> {
    // 1. Check if a sidecar named "instr-core-api" exists (tauri sidecar mechanism).
    let sidecar = app
        .path()
        .resolve("instr-core-api", tauri::path::BaseDirectory::Resource);
    if let Ok(p) = sidecar {
        if p.exists() {
            return Some(p);
        }
    }

    // 2. Development fallback: look upward from src-tauri for the Python source.
    let manifest = std::env!("CARGO_MANIFEST_DIR");
    let dev_path = std::path::PathBuf::from(manifest)
        .join("..")
        .join("..")
        .join("src")
        .join("instr_core")
        .join("api_server.py");
    if dev_path.exists() {
        return Some(dev_path);
    }

    // 3. Production fallback: look in Resources next to the binary.
    let resource_dir = app.path().resource_dir().ok()?;
    let prod_path = resource_dir
        .join("python")
        .join("instr_core")
        .join("api_server.py");
    if prod_path.exists() {
        return Some(prod_path);
    }

    eprintln!("Warning: Could not find Python backend script (api_server.py).");
    eprintln!("The desktop UI will not be able to communicate with instruments.");
    None
}

/// Spawn the Python backend as a child process.
fn start_python_backend(script: &std::path::Path) -> std::io::Result<Child> {
    // Prefer `uv run` in development; fall back to `python` in production.
    let uv_available = Command::new("uv")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    let mut cmd = if uv_available {
        let mut c = Command::new("uv");
        c.arg("run").arg("python").arg(script);
        c
    } else {
        let mut c = Command::new("python");
        c.arg(script);
        c
    };

    cmd.env("INSTR_CORE_API_PORT", "8765")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    println!("Starting Python backend: {:?}", cmd);
    cmd.spawn()
}
