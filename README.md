# SPLIT//EAR - Cyberpunk Dual Channel Player

[![Render Deployment](https://img.shields.io/badge/Render-Live-brightgreen?style=flat-square&logo=render)](https://split-ear.onrender.com/)
[![GitHub Repo](https://img.shields.io/badge/GitHub-SPLIT--EAR-blue?style=flat-square&logo=github)](https://github.com/omkardiggi/SPLIT-EAR)

SPLIT//EAR is a next-generation, cyberpunk-themed dual-channel audio player and mixer. It allows you to play and blend two distinct audio sources simultaneously (Left and Right audio channels) while offering real-time synchronization across multiple devices in a collaborative room.

Live Demo: [https://split-ear.onrender.com/](https://split-ear.onrender.com/)

---

## Features

*   **Dual-Channel Mixing**: Independent playback, source configuration, volume controls, and mute functions for the **Left (Blue)** and **Right (Pink)** channels.
*   **Multi-Platform Audio Resolver**: Built-in backend extractor powered by `yt-dlp` supporting:
    *   **Spotify**: Scraping public embeds without API keys (tracks, albums, playlists up to 50 tracks).
    *   **YouTube & SoundCloud**: Dynamic video and audio search/extraction.
    *   **JioSaavn & Local Fallbacks**: Indian music streaming support and robust direct stream fallbacks.
    *   **Instagram & Facebook Reels**: Extracting audio tracks from social links.
    *   **Real-Time Sync Engine**: Utilizes Server-Sent Events (SSE) to sync room playback state, volumes, channel mapping, and playlist index in real-time across multiple devices.
    *   **Aesthetic Cyberpunk UI**: Sleek futuristic layout featuring glassmorphism, responsive grid layout, customized neon glowing buttons, and dynamic wave visualizers.

    ---

    ## Tech Stack

    *   **Backend**: Python, Flask, Flask-CORS, python-dotenv, Gunicorn, yt-dlp
    *   **Frontend**: Semantic HTML5, CSS3 Custom Properties (CSS variables), Vanilla JS (SSE API interface, AudioContext API / HTML5 Audio elements)

    ---

    ## Local Setup & Installation

    1.  **Clone the Repository**:
        ```bash
        git clone https://github.com/omkardiggi/SPLIT-EAR.git
        cd SPLIT-EAR
        ```
        2.  **Install Dependencies**:
            *   It is recommended to use a virtual environment:
                    ```bash
                    python -m venv venv
                    source venv/bin/activate  # On Windows: venv\Scripts\activate
                    pip install -r requirements.txt
                    ```

3.  **Environment Configuration**:
    *   Create a `.env` file in the root directory (you can copy `.env.example`):
            ```bash
            cp .env.example .env
            ```
    *   Open `.env` and configure the following variables:
        *   `PORT`: Port to run the Flask server (default: `5000`)
        *   `FLASK_ENV`: Set to `development` or `production`
        *   `SECRET_KEY`: A secure random key for session security

4.  **Run the Application**:
    ```bash
    python app.py
    ```
    *   Open your browser and navigate to `http://localhost:5000` (or the port configured in `.env`).

---

## Usage Guide

1.  **Select Audio Channels**:
    *   **Left Channel (Blue)** & **Right Channel (Pink)** can load separate tracks.
    *   Paste a valid audio link (YouTube, Spotify, SoundCloud, JioSaavn, etc.) into the input field for the respective channel and click **Load**.
2.  **Playback Controls**:
    *   Use the play, pause, and stop buttons to control individual tracks.
    *   Adjust the volume sliders for each channel to mix the audio levels.
    *   Toggle the mute buttons to instantly silence a channel.
3.  **Real-Time Room Sync**:
    *   Create or join a sync room by sharing the room ID.
    *   All participants in the same room will have their playback synchronized in real-time.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## License

This project is licensed under the MIT License.
