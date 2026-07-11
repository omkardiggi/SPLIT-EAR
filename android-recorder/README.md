# Split-Ear Android System Audio Capture Utility

This native Android application captures system audio (games, YouTube, Instagram, WhatsApp) on Android 10+ devices and streams it in real-time to the Split-Ear server to pan it to your selected earbud.

## How it works
1. The app requests **Media Projection** and **Audio Capture** permissions from Android.
2. It starts a background `Foreground Service` to keep capture active while you play games or scroll social media.
3. It initializes `AudioPlaybackCaptureConfiguration` to hook into system media/game output.
4. It streams the raw stereo PCM audio over WebSockets/HTTP directly to your Split-Ear session.

## Codebase Structure
* [AndroidManifest.xml](file:///c:/Users/omkardiggi/Downloads/blstr/android-recorder/app/src/main/AndroidManifest.xml): App permissions and service declarations.
* [AudioCaptureService.kt](file:///c:/Users/omkardiggi/Downloads/blstr/android-recorder/app/src/main/java/com/splitear/recorder/AudioCaptureService.kt): Foreground capture service and WebSocket audio streamer.
* [MainActivity.kt](file:///c:/Users/omkardiggi/Downloads/blstr/android-recorder/app/src/main/java/com/splitear/recorder/MainActivity.kt): User interface to join rooms and start capture.

## How to Build the APK
1. Open the `android-recorder` folder in **Android Studio**.
2. Let Gradle sync and build dependencies.
3. Click **Build > Build Bundle(s) / APK(s) > Build APK(s)**.
4. Copy the generated `app-debug.apk` to the root folder of your Python Split-Ear project, rename it to `splitear.apk`, and place it in the `static/` directory to serve it from the web downloader!
