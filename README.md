
  # Video Quality Checker App

  This is a code bundle for Video Quality Checker App. The original project is available at https://www.figma.com/design/BuO6Fg8gqUkHwAkVWvfe4r/Video-Quality-Checker-App.

  ## Running the code

  Run `npm i` to install the dependencies.

  Run `npm run dev` to start the development server.
  

## Termux daemon quick start

Run daemon commands from the daemon directory first; otherwise Python may make `castcast` look like a missing module instead of the package under `daemon/`:

```sh
cd VideoQualityCheckerApp/daemon
pkg install python ffmpeg
termux-setup-storage
python -m castcast --media-root /storage/emulated/0/Download/Chromecast serve
```

If you accidentally start a duplicate server or start it from the wrong place, use the built-in process controls instead of manually grepping for PIDs:

```sh
python -m castcast server status
python -m castcast server kill
python -m castcast serve --restart
```
