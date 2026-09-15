# Telegram File Server 🚀

A modern, high-performance, self-hosted Cloud Storage and Media Streaming Server powered by **FastAPI**, **React (TypeScript & Vite)**, **MongoDB**, **Pyrogram**, and **FFmpeg**. It transforms your private Telegram channels and groups into an unlimited personal cloud drive with Google Drive-like streaming, folder downloads, file management, real-time channel inbox syncing, and comprehensive storage analytics.

---

## ✨ Key Features

### 📥 Telegram Channel Inbox & Real-time Auto-Sync
- **Direct Telegram Channel Listener**: Any file, movie, document, photo, voice note, or audio forwarded or uploaded directly into your Telegram channel appears in your Web Drive **in real time**.
- **Dedicated Telegram Inbox**: A dedicated sidebar section displaying all directly forwarded or uploaded Telegram files. Move or copy them anywhere into your folders with a simple drag-and-drop or context menu action.
- **Intelligent Title Extraction**: Forwarded movies and videos without explicit Telegram filenames automatically extract clean titles from the first line of the caption (e.g. `Shin-chan Kaanta Laga [720P].mp4`) instead of generic random IDs (`Video_AgAD...`).
- **Offline Downtime Auto Catch-up (Downtime Sync)**:
  - *Startup Auto-Sync*: If the server was offline while files were uploaded to your channel, it automatically detects the last known message ID on startup and catches up all missed files in batches.
  - *On-Demand Tab Catch-up*: Visiting or refreshing the **Telegram Inbox** tab performs a fast, non-blocking sync check (1.2s timeout) so the latest files appear instantly without lagging the UI.

---

### 🗑️ Trash & Recycle Bin System
- **Safe Soft Delete**: Deleting files or folders moves them to the Trash instead of permanently deleting them. Folders moved to trash preserve their internal hierarchy and file relationships.
- **Dedicated Trash View**: Accessible directly from the sidebar with an amber notification banner and quick **Empty Trash** option.
- **1-Click Restore**: Easily restore any file or entire folder back to its original location (`file_path`) with a single click (↺) or via the context menu.
- **Permanent Deletion**: Choose **Delete Forever** or **Empty Trash** to permanently purge database entries and remove underlying Telegram messages via worker bots.

---

### 📊 Storage & Dashboard Analytics
- **Visual Cloud Storage Meter**: Real-time calculation of total cloud storage consumed (GB / TB) across all files in your drive.
- **Category Distribution Breakdown**: Interactive category cards with file counts and storage size for:
  - 🎬 **Videos** (`.mp4`, `.mkv`, `.webm`, `.avi`, etc.)
  - 🎵 **Audio & Voice Messages** (`.mp3`, `.flac`, `.wav`, `.ogg`, etc.)
  - 🖼️ **Images** (`.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, etc.)
  - 📄 **Documents** (`.pdf`, `.docx`, `.xlsx`, `.txt`, etc.)
  - 📦 **Archives** (`.zip`, `.rar`, `.7z`, `.tar`, etc.)
  - 📁 **Other Files**
- **Summary Metrics**: High-level counters for Total Files, Total Folders, Starred Items, and Trashed Size.
- **Top 10 Largest Files**: Interactive leaderboard of the biggest files stored on your Telegram cloud with rank badges, file names, parent folders, and exact file sizes.

---

### ⭐ Starred / Favorites
- **1-Click Star Toggle**: Mark any file or folder as favorite with the Star icon (★) from the grid, list view, or right-click context menu.
- **Dedicated Starred Filter**: Quickly access all your important files and folders across all directories in a single unified view.

---

### 🌐 Desktop & Mobile WebDAV Mount (RaiDrive / MiXplorer / Finder)
- **RFC 4918 Compliant WebDAV Server (`/webdav/`)**: Mount your Telegram cloud drive directly into Windows Explorer, macOS Finder, or mobile file managers like a local hard disk.
- **4 Virtual Root Folders**:
  - `📁 Home`: Full directory tree with customized folders.
  - `📁 Telegram Inbox`: Direct access to incoming channel files.
  - `📁 Starred`: Quick access to favorite items.
  - `📁 Trash`: Soft-deleted files with recycle bin behavior.
- **Full Read & Write Support**:
  - *High-Speed Streaming (`GET`, `HEAD`)*: Multi-bot parallel streaming with HTTP 206 Partial Content byte-range seeking for media playback in VLC, MX Player, etc.
  - *Drag-and-Drop Uploads (`PUT`)*: Upload files directly to Telegram channels through Windows Explorer or file managers.
  - *Folder Creation (`MKCOL`)*: Create folders seamlessly from any client.
  - *File Deletion (`DELETE`)*: Soft-delete to Trash from Home; permanent purge when deleting from Trash.
  - *Move & Rename (`MOVE`)*: Reorganize files and folders on-the-fly.
  - *RFC 4918 File Locking (`LOCK`, `UNLOCK`)*: Flawless compatibility with RaiDrive and Microsoft Office file locking handshakes.
- **Easy Setup UI**: Built-in "Connect Drive (WebDAV)" dialog in the web interface with one-click copy for Host, Port, and Path, plus dedicated step-by-step setup guides for **RaiDrive** (Windows) and **MiXplorer** (Android).

---

### 🔍 Comprehensive Multi-Field Filtering & Sorting
- **Available Everywhere**: Seamlessly integrated across **Home**, **Telegram Inbox**, **Starred**, and **Trash**.
- **Multi-Field Sorting**:
  - Sort by **Name** (A–Z / Z–A), **Date Modified** (Newest / Oldest), **File Size** (Largest / Smallest), and **Type** (Folders First).
- **Three-Dimensional Filtering**:
  - **Type Filter**: All, Folders, Videos, Images, Audio, Documents, and Archives.
  - **Size Filter**: All, Small (<10 MB), Medium (10–100 MB), Large (100 MB–1 GB), and Very Large (>1 GB).
  - **Date Filter**: All, Today, Last 7 Days, Last 30 Days, and This Year.
- **Dynamic Active Filter Pills**: Instantly clear individual filters or reset all with a single click.

---

### 🎬 Advanced Media Player & Streaming
- **Dynamic Multi-Resolution Ladder**: Switch between **4K (2160p)**, **2K (1440p)**, **1080p**, **720p**, **480p**, **360p**, **240p**, and **144p** on-the-fly.
  - *Intelligent Ladder Capping*: The player probes the native video resolution and automatically caps the menu so lower-resolution videos never show upscale options.
  - *Zero-CPU Direct Streaming*: **Auto (Original)** streams raw video directly from Telegram storage using HTTP Range Requests (`bytes=...`) at **0% server CPU**.
  - *Lightweight Transcoding*: Downscaled resolutions use single-thread ultrafast encoding with aggressive CPU protections.
- **Multi-Audio Track Switching**: Full support for multi-language movies and shows (e.g., English ↔ Hindi). Remuxes audio streams on-the-fly while copying video frames (`-c:v copy`), preserving 100% video quality with near-zero CPU usage.
- **Subtitles & Closed Captions (CC)**:
  - *Embedded Subtitle Extraction*: Automatically extracts embedded `.srt` / `.subrip` subtitle streams into standard WebVTT format on-the-fly.
  - *Custom Subtitle Upload*: Drag-and-drop or select any external `.srt` or `.vtt` file directly in the web player.
- **Timeline & Seek Synchronization**:
  - *Master Duration Shielding*: Prevents chunked fragmented MP4 streams from corrupting total movie duration.
  - *Stream Offset Tracking (`streamStartTime`)*: Eliminates timeline drift and progress bar jumping when switching qualities or audio tracks.
  - *Dual-Mode Seeking*: Smooth 60fps scrubbing with native HTTP Range seeking for direct streams and timestamp-offset restarts for transcoded streams.
  - *Cross-Platform Compatibility*: Fully responsive touch scrubbing, double-tap seek (±10s), keyboard shortcuts (Space, K, J, L, Arrow keys), and native Fullscreen.
- **External Player Integration**: Launch any stream directly into **VLC Media Player** (`vlc://`), **MX Player** / Android intent (`intent://`), or copy direct stream links with one click.

---

### 📚 In-Browser Document & E-Book Readers
- **PDF Viewer**: Embedded native PDF reader with zoom, page jump, and text search directly in the browser.
- **EPUB E-Book Reader**: Interactive reader with Table of Contents (TOC), page flip, font size controls, and reading progress.
- **Comic & Manga Reader (.cbz / .cbr)**: In-memory image unpacking supporting both **Webtoon continuous vertical scroll** and **Manga page-flip spread**.
- **Word Document (.docx) Preview**: Pure client-side Word document rendering to HTML DOM with 100% privacy.
- **Markdown & Code Viewer**: GitHub-flavored Markdown rendering and syntax-highlighted code viewer (`.py`, `.js`, `.ts`, `.json`, `.html`, `.css`, `.sh`, `.yml`, `.sql`, `.log`, `.txt`) with line formatting and 1-click copy.

---

### 🖼️ Advanced Image Lightbox Gallery
- **Folder Gallery Browsing**: Swipe or use keyboard arrow keys to browse through all images in the folder.
- **Pinch, Zoom & Pan**: Deep zoom up to 5x with mouse wheel, pinch-to-zoom, and drag panning.
- **Bottom Thumbnail Strip**: Interactive carousel strip to quickly jump between photos.
- **Tools**: Fullscreen, auto-play slideshow, and direct download.

---

### 🗜️ Cloud Zip & Archive Operations (Zero Client Bandwidth)
- **Archive Inspector ("Peek Inside")**: Inspect the full directory tree, file sizes, and dates inside any `.zip` archive without extracting.
- **Cloud-Side Extraction**: Extract entire ZIP archives directly into your Telegram storage channel without downloading files to your computer or phone.
- **Cloud-Side Compression**: Select any files and folders and click **Compress to ZIP** to create a new archive directly in the cloud.

---

### 📁 Google Drive-Style File & Folder Management
- **On-the-Fly Folder Zip Streaming**: Download entire folders as `.zip` archives generated dynamically in memory without saving intermediate files to the server's disk.
- **2GB Multi-Part Auto-Splitting**: For large folders exceeding 2GB (e.g., a 2.8GB folder), downloads are automatically split into manageable parts (Part 1 = 2GB, Part 2 = 800MB) with an interactive download dialog.
- **Folder Properties Dialog**: Instantly inspect recursive statistics for any folder, including total recursive file count and human-readable aggregate size.
- **Bi-Directional Telegram Sync**: Deleting files or folders in the web UI automatically removes the corresponding messages from your Telegram channels to prevent orphaned files.
- **Multi-Selection & Batch Actions**: Select multiple files or folders for bulk deletion, movement, or downloading.
- **Intuitive Navigation Bar**: Streamlined top bar with responsive search bar, quick layout toggles (Grid/List), and mobile drawer navigation.

---

### 👥 Authentication & Multi-Bot Architecture
- **Dual Authentication**:
  - *Local Accounts*: Built-in username/password authentication with configurable admin credentials and permission controls.
  - *Google OAuth 2.0*: Sign in with Google with whitelist access via `AUTHORIZED_ADMIN_EMAILS`.
- **Multi-Bot Worker Pool**: Scale downloads and streaming concurrency across up to 20 Telegram bots (`TOKEN0` to `TOKEN19`) using intelligent round-robin and least-busy client scheduling.
- **MongoDB Caching**: Fast persistent caching of probed media metadata (codecs, resolutions, audio tracks, subtitles) to deliver instantaneous player initialization.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    Client["Client (Browser / Mobile / Desktop)"]
    FastAPI["FastAPI Backend Server (:8000)"]
    Frontend["React + Vite UI (TailwindCSS)"]
    FFmpeg["FFmpeg & FFprobe Engine"]
    MongoDB[("MongoDB (Metadata & Files)")]
    BotManager["Multi-Bot Worker Pool (Pyrogram)"]
    Listener["Channel Listener & Sync Engine"]
    Telegram[("Telegram Cloud Storage")]

    Client <-->|REST API / HTTP Stream| FastAPI
    Client <-->|Static UI Assets| Frontend
    FastAPI <-->|Probe / Transcode / Subtitles| FFmpeg
    FastAPI <-->|User & File Metadata| MongoDB
    FastAPI <-->|Download / Upload / Stream Parts| BotManager
    BotManager <-->|MTProto (8+ Bot Clients)| Telegram
    Listener <-->|Real-time Events & Auto Catch-up| Telegram
    Listener -->|Store Discovered Media| MongoDB
```

---

## 🚀 Quick Start (Docker Recommended)

### 1. Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/)
- Telegram API credentials (`API_ID` & `API_HASH` from [my.telegram.org](https://my.telegram.org))
- At least one Telegram bot token from [@BotFather](https://t.me/BotFather)

### 2. Clone the Repository
```bash
git clone https://github.com/yashsaxena15/TelegramFileServer.git
cd TelegramFileServer
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your settings:
```env
API_ID=12345678
API_HASH=your_telegram_api_hash
OWNER=your_telegram_user_id
TOKEN0=1245345768:your_primary_bot_token
DATABASE_URL=mongodb://mongo:27017/TelegramFileServer
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=your_secure_password
```

### 4. Build and Run
```bash
docker compose up -d --build
```
Access the web dashboard at: **`http://localhost:9000`** (or `http://localhost:8000` if bound directly).

---

## 💻 Manual Installation (Without Docker)

### Prerequisites
- Python 3.12+
- Node.js 18+ and `npm`
- FFmpeg & FFprobe (`sudo apt-get install -y ffmpeg`)
- MongoDB 6.0+ instance running locally or on MongoDB Atlas

### 1. Backend Setup
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Frontend Setup
```bash
cd src/frontend
npm install
npm run build
cd ../..
```

### 3. Start the Application
```bash
python __main__.py
```

---

## ⚙️ Environment Variables Reference

| Variable | Description | Required | Default |
|:---|:---|:---:|:---|
| `API_ID` | Telegram API ID from [my.telegram.org](https://my.telegram.org) | **Yes** | — |
| `API_HASH` | Telegram API Hash from [my.telegram.org](https://my.telegram.org) | **Yes** | — |
| `OWNER` | Telegram Numerical User ID of the primary administrator | **Yes** | — |
| `TOKEN0` | Primary Telegram Bot Token from [@BotFather](https://t.me/BotFather) | **Yes** | — |
| `TOKEN1`..`TOKEN19` | Additional bot tokens for concurrent download pooling | No | — |
| `LOGGER_BOT` | Bot token dedicated for logging system events | No | `TOKEN0` |
| `DATABASE_URL` | MongoDB connection string (local or MongoDB Atlas) | **Yes** | `mongodb://mongo:27017` |
| `PORT` | Web server listening port | No | `8000` |
| `HOST` | Web server bind address | No | `0.0.0.0` |
| `WEB_APP` | Public URL / Reverse Proxy URL of the web server | No | `http://localhost:8000` |
| `SESSION_SECRET_KEY` | Secret key for signing session cookies | No | Auto-configured |
| `DEFAULT_ADMIN_USERNAME` | Default local admin username | No | `admin` |
| `DEFAULT_ADMIN_PASSWORD` | Default local admin password | No | `password` |
| `AUTHORIZED_ADMIN_EMAILS` | Comma-separated list of Google OAuth admin emails | No | — |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID for Google Sign-In | No | — |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Client Secret | No | — |
| `LOGS` | Telegram channel ID for storing activity logs | No | — |
| `MOVIE` / `MOVIE_GRP` | Telegram channel IDs for categorized media indexing | No | — |
| `FILTER_CHAT` | Telegram channel ID for filter bot storage | No | — |

---

## 🛠️ API Overview

- **`GET /files`**: Fetch all files and folders for a given path (supports `/Home`, `/inbox`, `/starred`, `/trash`).
- **`GET /dl/{file_name}`**: High-speed direct media streaming supporting HTTP/1.1 Range Requests.
- **`GET /media/info/{file_name}`**: Probe video resolution, audio tracks, and embedded subtitles.
- **`GET /media/stream/{file_name}`**: Dynamic on-the-fly resolution downscaling and audio track remuxing.
- **`GET /media/subtitles/{file_name}`**: Real-time extraction of embedded subtitle tracks to WebVTT.
- **`POST /files/move`**: Move file or folder to a target path.
- **`POST /files/copy`**: Copy file or folder to a target path.
- **`POST /files/star`**: Toggle starred state on an item.
- **`POST /files/trash`**: Soft delete item to Trash.
- **`POST /files/restore`**: Restore item from Trash back to its original location.
- **`DELETE /files/trash/empty`**: Permanently purge all items currently in Trash.
- **`GET /files/analytics`**: Retrieve storage analytics, category breakdown, and top 10 largest files.
- **`GET /api/folders/download/{folder_id}`**: On-the-fly multi-part Zip streaming for entire folders.
- **`GET /api/folders/properties/{folder_id}`**: Recursive file count and size calculations.
- **`POST /api/auth/login`**: User authentication (local credentials and session tokens).
- **`PROPFIND /webdav/{path}`**: WebDAV directory listing and metadata retrieval (Home, Inbox, Starred, Trash).
- **`GET /webdav/{path}`**: High-speed WebDAV streaming and file download with byte-range support.
- **`PUT /webdav/{path}`**: WebDAV file upload pipeline directly to Telegram storage.
- **`MKCOL /webdav/{path}`**: WebDAV folder creation.
- **`DELETE /webdav/{path}`**: WebDAV file and folder deletion (soft-delete to Trash / permanent purge).
- **`MOVE /webdav/{path}`**: WebDAV file and folder renaming and movement across directories.
- **`LOCK / UNLOCK /webdav/{path}`**: WebDAV active lock token handshakes for desktop mounting.

Interactive OpenAPI documentation is available at **`/docs`** when the server is running.

---

## 📄 License & Attribution

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

- **Original Author**: Copyright (c) 2025 P A M O D ([FileServerApp](https://github.com/pamod-madubashana/FileServerApp))
- **Extended & Maintained**: Copyright (c) 2026 TelegramFileServer Contributors