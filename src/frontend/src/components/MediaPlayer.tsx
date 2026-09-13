import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Volume2,
  Volume1,
  VolumeX,
  Settings,
  Maximize,
  Minimize,
  PictureInPicture2,
  Captions,
  Check,
  Download,
  X,
  ArrowLeft,
  Info,
  FileAudio,
  ChevronRight,
  Search,
  SlidersHorizontal,
  FileText,
  List,
  AlertCircle,
  ExternalLink,
} from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";
import { downloadManager } from "@/lib/downloadManager";
import { toast } from "sonner";

interface MediaPlayerProps {
  mediaUrl: string;
  fileName: string;
  fileType: "video" | "audio" | "voice";
  startPosition?: { x: number; y: number; width: number; height: number };
  onClose: () => void;
  onDownload?: () => void;
}

const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

const formatTime = (seconds: number): string => {
  if (isNaN(seconds) || !isFinite(seconds) || seconds < 0) {
    return "0:00";
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }
  return `${m}:${s.toString().padStart(2, "0")}`;
};

const getFileExtension = (name: string): string => {
  const parts = name.split(".");
  if (parts.length > 1) {
    return parts.pop()?.toUpperCase() || "MEDIA";
  }
  return "MEDIA";
};

export const MediaPlayer = ({
  mediaUrl,
  fileName,
  fileType,
  startPosition,
  onClose,
  onDownload,
}: MediaPlayerProps) => {
  const isMobile = useIsMobile();
  const isAudio = fileType === "audio" || fileType === "voice";

  const fullMediaUrl = useMemo(() => {
    if (!mediaUrl) return "";
    if (mediaUrl.startsWith("http://") || mediaUrl.startsWith("https://")) {
      return mediaUrl;
    }
    if (typeof window !== "undefined") {
      return `${window.location.origin}${mediaUrl.startsWith("/") ? "" : "/"}${mediaUrl}`;
    }
    return mediaUrl;
  }, [mediaUrl]);

  // Elements
  const containerRef = useRef<HTMLDivElement>(null);
  const mediaElementRef = useRef<HTMLVideoElement | HTMLAudioElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const controlsTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const singleTapTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastTapTimeRef = useRef<number>(0);
  const lastTapZoneRef = useRef<"left" | "right" | "center">("center");
  const retryCountRef = useRef<number>(0);

  // Playback states
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [bufferedEnd, setBufferedEnd] = useState(0);
  const [volume, setVolume] = useState(() => {
    const saved = localStorage.getItem("player_volume");
    return saved !== null ? parseFloat(saved) : 1.0;
  });
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [isBuffering, setIsBuffering] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isPiPActive, setIsPiPActive] = useState(false);
  const [canPiP, setCanPiP] = useState(false);

  // UI visibility states
  const [areControlsVisible, setAreControlsVisible] = useState(true);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [hoverPosPercent, setHoverPosPercent] = useState<number>(0);
  const [videoDimensions, setVideoDimensions] = useState<{ width: number; height: number } | null>(null);

  // Active overlays / submenus: 'none' | 'settings' | 'speed' | 'quality' | 'subtitles' | 'chapters' | 'transcript' | 'info'
  const [activeMenu, setActiveMenu] = useState<string>("none");
  const [transcriptSearch, setTranscriptSearch] = useState("");

  // Visual feedback states
  const [rippleFeedback, setRippleFeedback] = useState<{
    type: "forward" | "rewind" | "play" | "pause";
    id: number;
  } | null>(null);
  const [centralPulse, setCentralPulse] = useState<"play" | "pause" | null>(null);
  const lastNonZeroVolume = useRef(volume > 0 ? volume : 1.0);

  // Check PiP capability on mount
  useEffect(() => {
    if (typeof document !== "undefined") {
      setCanPiP(
        "pictureInPictureEnabled" in document && (document as any).pictureInPictureEnabled
      );
    }
  }, []);

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

  // Clean, deterministic controls visibility management
  const showControls = useCallback((delay = 4500) => {
    setAreControlsVisible(true);
    if (controlsTimeoutRef.current) {
      clearTimeout(controlsTimeoutRef.current);
      controlsTimeoutRef.current = null;
    }
    // Only auto-hide when playing, not scrubbing, and no modal menu is open
    if (isPlaying && !isScrubbing && activeMenu === "none") {
      controlsTimeoutRef.current = setTimeout(() => {
        setAreControlsVisible(false);
      }, delay);
    }
  }, [isPlaying, isScrubbing, activeMenu]);

  const hideControls = useCallback(() => {
    if (controlsTimeoutRef.current) {
      clearTimeout(controlsTimeoutRef.current);
      controlsTimeoutRef.current = null;
    }
    if (activeMenu === "none" && !isScrubbing) {
      setAreControlsVisible(false);
    }
  }, [activeMenu, isScrubbing]);

  // When playing state or active menu changes, update timeout
  useEffect(() => {
    if (isPlaying && activeMenu === "none" && !isScrubbing) {
      showControls(4500);
    } else {
      // Keep controls visible when paused or menu is open
      setAreControlsVisible(true);
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
        controlsTimeoutRef.current = null;
      }
    }
    return () => {
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [isPlaying, activeMenu, isScrubbing, showControls]);

  // Clean up timers on unmount
  useEffect(() => {
    return () => {
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
      if (singleTapTimerRef.current) {
        clearTimeout(singleTapTimerRef.current);
      }
    };
  }, []);

  // Video/Audio playback actions
  const togglePlay = useCallback(() => {
    const el = mediaElementRef.current;
    if (!el) return;
    if (el.paused) {
      el.play().then(() => {
        setIsPlaying(true);
        setCentralPulse("play");
        setTimeout(() => setCentralPulse(null), 500);
        showControls(4500);
      }).catch((err) => {
        console.warn("Play failed:", err);
      });
    } else {
      el.pause();
      setIsPlaying(false);
      setCentralPulse("pause");
      setTimeout(() => setCentralPulse(null), 500);
      setAreControlsVisible(true);
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
        controlsTimeoutRef.current = null;
      }
    }
  }, [showControls]);

  const seekRelative = useCallback((deltaSeconds: number) => {
    const el = mediaElementRef.current;
    if (!el) return;
    const target = Math.min(Math.max(0, el.currentTime + deltaSeconds), el.duration || 0);
    el.currentTime = target;
    setCurrentTime(target);
    const type = deltaSeconds < 0 ? "rewind" : "forward";
    setRippleFeedback({ type, id: Date.now() });
    setTimeout(() => {
      setRippleFeedback((prev) => (prev?.type === type ? null : prev));
    }, 600);
    showControls(4500);
  }, [showControls]);

  const handleVolumeChange = useCallback((newVol: number) => {
    const el = mediaElementRef.current;
    const clamped = Math.min(1, Math.max(0, newVol));
    setVolume(clamped);
    localStorage.setItem("player_volume", clamped.toString());
    if (clamped > 0) {
      lastNonZeroVolume.current = clamped;
      setIsMuted(false);
    } else {
      setIsMuted(true);
    }
    if (el) {
      el.volume = clamped;
      el.muted = clamped === 0;
    }
    showControls(4500);
  }, [showControls]);

  const toggleMute = useCallback(() => {
    const el = mediaElementRef.current;
    if (!el) return;
    if (isMuted || volume === 0) {
      const restored = lastNonZeroVolume.current || 1.0;
      setVolume(restored);
      setIsMuted(false);
      el.volume = restored;
      el.muted = false;
    } else {
      lastNonZeroVolume.current = volume;
      setVolume(0);
      setIsMuted(true);
      el.volume = 0;
      el.muted = true;
    }
    showControls(4500);
  }, [isMuted, volume, showControls]);

  const handlePlaybackRateChange = useCallback((rate: number) => {
    const el = mediaElementRef.current;
    setPlaybackRate(rate);
    if (el) {
      el.playbackRate = rate;
    }
    showControls(4500);
  }, [showControls]);

  const toggleFullscreen = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    if (!document.fullscreenElement) {
      container.requestFullscreen?.().catch((err) => console.warn("Fullscreen request error:", err));
    } else {
      document.exitFullscreen?.().catch((err) => console.warn("Exit fullscreen error:", err));
    }
    showControls(4500);
  }, [showControls]);

  const togglePiP = useCallback(async () => {
    const video = mediaElementRef.current as HTMLVideoElement;
    if (!video || !canPiP) return;
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
        setIsPiPActive(false);
      } else {
        await video.requestPictureInPicture();
        setIsPiPActive(true);
      }
    } catch (err) {
      console.warn("PiP toggle error:", err);
    }
    showControls(4500);
  }, [canPiP, showControls]);

  const handleDownloadAction = useCallback(() => {
    if (onDownload) {
      onDownload();
    } else {
      downloadManager.addDownload(mediaUrl, fileName);
      toast.success(`Download started: ${fileName}`);
    }
  }, [onDownload, mediaUrl, fileName]);

  // Timeline Scrubbing Handlers
  const handleTimelinePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const timeline = timelineRef.current;
    const el = mediaElementRef.current;
    if (!timeline || !el || !duration) return;

    (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
    setIsScrubbing(true);
    setAreControlsVisible(true);

    const rect = timeline.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const newTime = ratio * duration;
    el.currentTime = newTime;
    setCurrentTime(newTime);
  };

  const handleTimelinePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const timeline = timelineRef.current;
    const el = mediaElementRef.current;
    if (!timeline || !duration) return;

    const rect = timeline.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const newTime = ratio * duration;

    setHoverPosPercent(ratio * 100);
    setHoverTime(newTime);

    if (isScrubbing && el) {
      el.currentTime = newTime;
      setCurrentTime(newTime);
    }
  };

  const handleTimelinePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isScrubbing) {
      try {
        (e.currentTarget as HTMLDivElement).releasePointerCapture(e.pointerId);
      } catch {}
      setIsScrubbing(false);
      showControls(4500);
    }
  };

  const handleTimelinePointerLeave = () => {
    if (!isScrubbing) {
      setHoverTime(null);
    }
  };

  // Keyboard Shortcuts (Desktop)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const active = document.activeElement;
      if (
        active &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          (active as HTMLElement).isContentEditable)
      ) {
        return;
      }

      switch (e.key) {
        case " ":
        case "k":
        case "K":
          e.preventDefault();
          togglePlay();
          break;
        case "ArrowLeft":
        case "j":
        case "J":
          e.preventDefault();
          seekRelative(-10);
          break;
        case "ArrowRight":
        case "l":
        case "L":
          e.preventDefault();
          seekRelative(10);
          break;
        case "ArrowUp":
          e.preventDefault();
          handleVolumeChange(volume + 0.1);
          break;
        case "ArrowDown":
          e.preventDefault();
          handleVolumeChange(volume - 0.1);
          break;
        case "m":
        case "M":
          e.preventDefault();
          toggleMute();
          break;
        case "f":
        case "F":
          e.preventDefault();
          toggleFullscreen();
          break;
        case "Escape":
          if (isFullscreen) {
            document.exitFullscreen?.();
          } else if (activeMenu !== "none") {
            setActiveMenu("none");
          } else {
            onClose();
          }
          break;
        case "<":
        case ",": {
          e.preventDefault();
          const currentIndex = PLAYBACK_RATES.indexOf(playbackRate);
          if (currentIndex > 0) {
            handlePlaybackRateChange(PLAYBACK_RATES[currentIndex - 1]);
          }
          break;
        }
        case ">":
        case ".": {
          e.preventDefault();
          const currentIndex = PLAYBACK_RATES.indexOf(playbackRate);
          if (currentIndex < PLAYBACK_RATES.length - 1) {
            handlePlaybackRateChange(PLAYBACK_RATES[currentIndex + 1]);
          }
          break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    togglePlay,
    seekRelative,
    handleVolumeChange,
    volume,
    toggleMute,
    toggleFullscreen,
    isFullscreen,
    activeMenu,
    onClose,
    playbackRate,
    handlePlaybackRateChange,
  ]);

  // Robust Viewport Pointer/Tap Handler:
  // Handles Single Tap (Toggle controls on touch / Play-Pause on desktop)
  // and Double Tap (Seek -10s left / +10s right) without race conditions.
  const handleViewportPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    // If a menu or modal is open, tapping the viewport closes it and reveals controls
    if (activeMenu !== "none") {
      setActiveMenu("none");
      showControls(4500);
      return;
    }

    const isTouch = e.pointerType === "touch" || e.pointerType === "pen";
    const rect = e.currentTarget.getBoundingClientRect();
    const xRatio = (e.clientX - rect.left) / rect.width;
    let zone: "left" | "right" | "center" = "center";
    if (xRatio < 0.35) zone = "left";
    else if (xRatio > 0.65) zone = "right";

    const now = Date.now();
    const timeSinceLastTap = now - lastTapTimeRef.current;
    const isDoubleTap = timeSinceLastTap < 300 && lastTapZoneRef.current === zone;

    if (isDoubleTap) {
      // Double-tap detected: cancel single-tap action
      if (singleTapTimerRef.current) {
        clearTimeout(singleTapTimerRef.current);
        singleTapTimerRef.current = null;
      }
      lastTapTimeRef.current = 0;
      lastTapZoneRef.current = "center";

      if (zone === "left") {
        seekRelative(-10);
      } else if (zone === "right") {
        seekRelative(10);
      } else {
        togglePlay();
      }
      showControls(4500);
    } else {
      // First tap: register timestamp and schedule single-tap action
      lastTapTimeRef.current = now;
      lastTapZoneRef.current = zone;

      if (singleTapTimerRef.current) {
        clearTimeout(singleTapTimerRef.current);
      }

      singleTapTimerRef.current = setTimeout(() => {
        singleTapTimerRef.current = null;

        if (isTouch) {
          // On touch screens: single tap toggles controls visibility
          setAreControlsVisible((prev) => {
            if (!prev) {
              // If controls were hidden, show them and keep visible for 4.5s
              showControls(4500);
              return true;
            } else {
              // If controls were already visible, hide them immediately
              hideControls();
              return false;
            }
          });
        } else {
          // On desktop mouse: single click toggles play/pause
          togglePlay();
        }
      }, 260);
    }
  };

  // Video event listeners
  const handleTimeUpdate = () => {
    const el = mediaElementRef.current;
    if (!el || isScrubbing) return;
    setCurrentTime(el.currentTime);
  };

  const handleProgress = () => {
    const el = mediaElementRef.current;
    if (!el || !el.buffered || el.buffered.length === 0) return;
    const current = el.currentTime;
    for (let i = 0; i < el.buffered.length; i++) {
      if (el.buffered.start(i) <= current && current <= el.buffered.end(i)) {
        setBufferedEnd(el.buffered.end(i));
        return;
      }
    }
    setBufferedEnd(el.buffered.end(el.buffered.length - 1));
  };

  const handleLoadedMetadata = () => {
    const el = mediaElementRef.current;
    if (!el) return;
    setDuration(el.duration || 0);
    if (!isAudio && el instanceof HTMLVideoElement) {
      setVideoDimensions({ width: el.videoWidth, height: el.videoHeight });
    }
    setIsBuffering(false);
  };

  const playedPercent = useMemo(() => {
    if (!duration || duration === 0) return 0;
    return Math.min(100, Math.max(0, (currentTime / duration) * 100));
  }, [currentTime, duration]);

  const bufferedPercent = useMemo(() => {
    if (!duration || duration === 0) return 0;
    return Math.min(100, Math.max(0, (bufferedEnd / duration) * 100));
  }, [bufferedEnd, duration]);

  const fileExt = useMemo(() => getFileExtension(fileName), [fileName]);

  // If file is Audio or Voice, render Google Drive dark glassmorphic audio widget
  if (isAudio) {
    return (
      <div
        className="fixed bottom-4 left-4 right-4 sm:left-auto sm:right-6 sm:w-96 backdrop-blur-xl bg-zinc-950/95 text-white border border-white/10 rounded-2xl shadow-2xl z-50 p-4 transition-all duration-300 select-none animate-in fade-in slide-in-from-bottom-4"
        style={{
          boxShadow: "0 20px 40px -15px rgba(0,0,0,0.8), 0 0 1px 1px rgba(255,255,255,0.1)",
        }}
      >
        <audio
          ref={mediaElementRef as any}
          src={mediaUrl}
          preload="auto"
          autoPlay
          onTimeUpdate={handleTimeUpdate}
          onProgress={handleProgress}
          onLoadedMetadata={handleLoadedMetadata}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onWaiting={() => setIsBuffering(true)}
          onPlaying={() => setIsBuffering(false)}
          onCanPlay={() => setIsBuffering(false)}
          onError={() => setIsBuffering(false)}
        />

        {/* Top bar with Title & Badge */}
        <div className="flex items-center justify-between pb-3 border-b border-white/10">
          <div className="flex items-center space-x-2.5 min-w-0 pr-2">
            <div className="w-8 h-8 rounded-lg bg-blue-500/20 text-blue-400 flex items-center justify-center flex-shrink-0 border border-blue-500/30">
              <FileAudio className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium truncate text-white/95">{fileName}</div>
              <div className="flex items-center space-x-2 text-[11px] text-white/50">
                <span className="font-mono uppercase">{fileExt}</span>
                <span>•</span>
                <span>{fileType === "voice" ? "Voice Message" : "Audio Track"}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center space-x-1 flex-shrink-0">
            <button
              onClick={handleDownloadAction}
              className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors"
              title="Download audio"
              aria-label="Download audio"
            >
              <Download className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors"
              title="Close player"
              aria-label="Close player"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Timeline */}
        <div className="pt-3 pb-1">
          <div
            ref={timelineRef}
            onPointerDown={handleTimelinePointerDown}
            onPointerMove={handleTimelinePointerMove}
            onPointerUp={handleTimelinePointerUp}
            onPointerLeave={handleTimelinePointerLeave}
            className="group relative h-4 flex items-center cursor-pointer touch-none"
          >
            <div className="w-full h-1.5 bg-white/20 rounded-full relative overflow-hidden group-hover:h-2 transition-all">
              <div
                className="absolute left-0 top-0 h-full bg-white/30 rounded-full transition-all duration-150"
                style={{ width: `${bufferedPercent}%` }}
              />
              <div
                className="absolute left-0 top-0 h-full bg-blue-500 rounded-full transition-all duration-100"
                style={{ width: `${playedPercent}%` }}
              />
            </div>
            {/* Scrubber thumb */}
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 bg-white rounded-full shadow-md scale-0 group-hover:scale-100 transition-transform pointer-events-none"
              style={{ left: `${playedPercent}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-xs text-white/60 font-mono pt-1">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        {/* Audio Controls */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center space-x-1">
            <button
              onClick={() => seekRelative(-10)}
              className="p-2 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-colors relative"
              title="Rewind 10 seconds"
              aria-label="Rewind 10 seconds"
            >
              <RotateCcw className="w-4 h-4" />
              <span className="absolute text-[8px] font-bold top-2 left-2">10</span>
            </button>
            <button
              onClick={togglePlay}
              className="p-2.5 rounded-full bg-blue-600 hover:bg-blue-500 text-white shadow-lg transition-transform active:scale-95"
              title={isPlaying ? "Pause" : "Play"}
              aria-label={isPlaying ? "Pause" : "Play"}
            >
              {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current ml-0.5" />}
            </button>
            <button
              onClick={() => seekRelative(10)}
              className="p-2 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-colors relative"
              title="Forward 10 seconds"
              aria-label="Forward 10 seconds"
            >
              <RotateCw className="w-4 h-4" />
              <span className="absolute text-[8px] font-bold top-2 left-2">10</span>
            </button>
          </div>

          {/* Volume & Speed */}
          <div className="flex items-center space-x-2">
            <button
              onClick={() => {
                const nextRates = [1, 1.25, 1.5, 2, 0.75];
                const next = nextRates[(nextRates.indexOf(playbackRate) + 1) % nextRates.length];
                handlePlaybackRateChange(next);
              }}
              className="px-2 py-1 text-xs font-mono rounded-md hover:bg-white/10 text-white/75 hover:text-white border border-white/10 transition-colors"
              title="Playback speed"
            >
              {playbackRate}x
            </button>
            <div className="flex items-center space-x-1 group">
              <button
                onClick={toggleMute}
                className="p-1.5 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-colors"
                title={isMuted ? "Unmute" : "Mute"}
                aria-label={isMuted ? "Unmute" : "Mute"}
              >
                {isMuted || volume === 0 ? (
                  <VolumeX className="w-4 h-4" />
                ) : volume < 0.5 ? (
                  <Volume1 className="w-4 h-4" />
                ) : (
                  <Volume2 className="w-4 h-4" />
                )}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={isMuted ? 0 : volume}
                onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
                className="w-16 h-1 accent-blue-500 bg-white/20 rounded-full cursor-pointer"
                aria-label="Volume slider"
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  // =========================================================================
  // Google Drive Style Video Player
  // =========================================================================
  return (
    <div
      ref={containerRef}
      onMouseMove={() => showControls(4000)}
      className={`fixed inset-0 z-50 bg-[#0a0a0a] text-white flex flex-col select-none overflow-hidden ${
        !areControlsVisible && isPlaying ? "cursor-none" : "cursor-default"
      }`}
    >
      {/* Native Video Element */}
      <video
        ref={mediaElementRef as any}
        src={mediaUrl}
        preload="auto"
        playsInline
        className="w-full h-full object-contain pointer-events-none"
        onTimeUpdate={handleTimeUpdate}
        onProgress={handleProgress}
        onLoadedMetadata={handleLoadedMetadata}
        onPlay={() => {
          setIsPlaying(true);
          showControls(4500);
        }}
        onPause={() => {
          setIsPlaying(false);
          setAreControlsVisible(true);
        }}
        onEnded={() => {
          setIsPlaying(false);
          setAreControlsVisible(true);
        }}
        onWaiting={() => setIsBuffering(true)}
        onPlaying={() => {
          setIsBuffering(false);
          setHasPlaybackError(false);
        }}
        onCanPlay={() => {
          setIsBuffering(false);
          setHasPlaybackError(false);
        }}
        onError={() => {
          const videoEl = mediaElementRef.current as HTMLVideoElement;
          const err = videoEl?.error;
          console.warn("Video playback error code:", err?.code, err?.message);

          // Code 1: MEDIA_ERR_ABORTED - aborted by browser during seek or range change
          if (err && err.code === 1) {
            return;
          }

          // Code 2: MEDIA_ERR_NETWORK - network issue or temporary Telegram hiccup
          if (err && err.code === 2) {
            if (retryCountRef.current < 3) {
              retryCountRef.current += 1;
              console.log("Retrying video playback after network error, attempt:", retryCountRef.current);
              setIsBuffering(true);
              setTimeout(() => {
                if (mediaElementRef.current) {
                  mediaElementRef.current.load();
                  mediaElementRef.current.play().catch(() => {});
                }
              }, 1200);
              return;
            }
          }

          // Keep attempting playback or buffering without blocking modal
          setIsBuffering(false);
        }}
      />

      {/* Interactive Video Viewport: Double-tap left/right & Tap to toggle controls */}
      <div
        className="absolute inset-0 z-10 touch-manipulation cursor-pointer"
        onPointerUp={handleViewportPointerUp}
      />

      {/* Buffering Spinner */}
      {isBuffering && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-20 pointer-events-none">
          <div className="w-14 h-14 rounded-full border-4 border-white/20 border-t-white animate-spin mb-3 shadow-lg" />
          <span className="text-xs sm:text-sm text-white/80 font-medium tracking-wide drop-shadow-md">
            Buffering video stream...
          </span>
        </div>
      )}

      {/* Central Play/Pause Pulse Feedback */}
      {centralPulse && (
        <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none animate-out fade-out zoom-out-95 duration-500">
          <div className="w-20 h-20 rounded-full bg-black/60 backdrop-blur-md border border-white/20 flex items-center justify-center text-white shadow-2xl">
            {centralPulse === "play" ? (
              <Play className="w-10 h-10 fill-current ml-1" />
            ) : (
              <Pause className="w-10 h-10 fill-current" />
            )}
          </div>
        </div>
      )}

      {/* Double Tap Ripple Animations (+10s / -10s) */}
      {rippleFeedback && (
        <div
          className={`absolute top-1/2 -translate-y-1/2 z-20 pointer-events-none flex flex-col items-center justify-center w-32 h-32 sm:w-36 sm:h-36 rounded-full bg-black/65 backdrop-blur-md border border-white/20 animate-in fade-in zoom-in-75 duration-200 ${
            rippleFeedback.type === "rewind" ? "left-8 sm:left-24" : "right-8 sm:right-24"
          }`}
        >
          {rippleFeedback.type === "rewind" ? (
            <>
              <RotateCcw className="w-9 h-9 sm:w-10 sm:h-10 text-white animate-spin-once" />
              <span className="text-xs sm:text-sm font-bold tracking-wider text-white mt-1">-10s</span>
            </>
          ) : (
            <>
              <RotateCw className="w-9 h-9 sm:w-10 sm:h-10 text-white animate-spin-once" />
              <span className="text-xs sm:text-sm font-bold tracking-wider text-white mt-1">+10s</span>
            </>
          )}
        </div>
      )}

      {/* ================================================================= */}
      {/* Top Header Bar (Google Drive Style)                                */}
      {/* ================================================================= */}
      <div
        onClick={(e) => {
          e.stopPropagation();
          showControls(5000);
        }}
        onPointerDown={(e) => {
          e.stopPropagation();
          showControls(5000);
        }}
        className={`absolute top-0 left-0 right-0 z-30 transition-all duration-300 ease-out bg-gradient-to-b from-black/90 via-black/50 to-transparent pt-3 pb-8 px-3 sm:px-6 flex items-center justify-between ${
          areControlsVisible || !isPlaying || activeMenu !== "none"
            ? "opacity-100 translate-y-0"
            : "opacity-0 -translate-y-full pointer-events-none"
        }`}
      >
        {/* Left: Back Arrow + Title + Format Badge */}
        <div className="flex items-center space-x-2 sm:space-x-3 min-w-0 pr-2">
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-white/10 text-white/90 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[40px] min-h-[40px] flex items-center justify-center"
            title="Back / Close"
            aria-label="Back / Close"
          >
            <ArrowLeft className="w-5 h-5 sm:w-6 sm:h-6" />
          </button>
          <div className="flex items-center space-x-2 min-w-0">
            <span className="text-white text-sm sm:text-base font-semibold truncate max-w-[170px] sm:max-w-md md:max-w-xl lg:max-w-2xl drop-shadow-sm">
              {fileName}
            </span>
            <span className="px-1.5 py-0.5 text-[10px] sm:text-xs font-mono font-bold uppercase rounded bg-white/15 text-white/80 border border-white/10 flex-shrink-0 tracking-wider">
              {fileExt}
            </span>
          </div>
        </div>

        {/* Right: Actions (External Player, Download, Info, Close) */}
        <div className="flex items-center space-x-0.5 sm:space-x-1 flex-shrink-0">
          <button
            onClick={() => {
              setActiveMenu((prev) => (prev === "external" ? "none" : "external"));
              showControls(5000);
            }}
            className={`p-2 rounded-full hover:bg-white/10 text-white/90 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[40px] min-h-[40px] flex items-center justify-center ${
              activeMenu === "external" ? "bg-blue-600 text-white" : ""
            }`}
            title="Open in external player (VLC / MX Player)"
            aria-label="Open in external player"
          >
            <ExternalLink className="w-5 h-5" />
          </button>
          <button
            onClick={handleDownloadAction}
            className="p-2 rounded-full hover:bg-white/10 text-white/90 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[40px] min-h-[40px] flex items-center justify-center"
            title="Download file"
            aria-label="Download file"
          >
            <Download className="w-5 h-5" />
          </button>
          <button
            onClick={() => setActiveMenu((prev) => (prev === "info" ? "none" : "info"))}
            className={`p-2 rounded-full hover:bg-white/10 text-white/90 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[40px] min-h-[40px] flex items-center justify-center ${
              activeMenu === "info" ? "bg-white/20 text-white" : ""
            }`}
            title="File details"
            aria-label="File details"
          >
            <Info className="w-5 h-5" />
          </button>
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-white/10 text-white/90 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[40px] min-h-[40px] flex items-center justify-center"
            title="Close viewer"
            aria-label="Close viewer"
          >
            <X className="w-5 h-5 sm:w-6 sm:h-6" />
          </button>
        </div>
      </div>

      {/* ================================================================= */}
      {/* Bottom Control Bar (Google Drive Style)                            */}
      {/* ================================================================= */}
      <div
        onClick={(e) => {
          e.stopPropagation();
          showControls(5000);
        }}
        onPointerDown={(e) => {
          e.stopPropagation();
          showControls(5000);
        }}
        className={`absolute bottom-0 left-0 right-0 z-30 transition-all duration-300 ease-out bg-gradient-to-t from-black/95 via-black/60 to-transparent pt-10 pb-3 sm:pb-4 px-3 sm:px-6 flex flex-col ${
          areControlsVisible || !isPlaying || activeMenu !== "none"
            ? "opacity-100 translate-y-0"
            : "opacity-0 translate-y-full pointer-events-none"
        }`}
      >
        {/* Timeline Scrubber */}
        <div className="relative w-full pb-1 sm:pb-2">
          {/* Hover Timestamp Tooltip */}
          {hoverTime !== null && (
            <div
              className="absolute -top-7 -translate-x-1/2 px-2 py-0.5 rounded bg-zinc-900/90 text-white text-[11px] font-mono border border-white/20 shadow-lg pointer-events-none"
              style={{ left: `${hoverPosPercent}%` }}
            >
              {formatTime(hoverTime)}
            </div>
          )}

          <div
            ref={timelineRef}
            onPointerDown={handleTimelinePointerDown}
            onPointerMove={handleTimelinePointerMove}
            onPointerUp={handleTimelinePointerUp}
            onPointerLeave={handleTimelinePointerLeave}
            className="group relative h-6 flex items-center cursor-pointer touch-none"
            aria-label="Seek timeline"
          >
            <div className="w-full h-1.5 group-hover:h-2.5 bg-white/20 rounded-full relative overflow-hidden transition-all duration-150">
              {/* Buffered progress bar */}
              <div
                className="absolute left-0 top-0 h-full bg-white/35 rounded-full transition-all duration-150"
                style={{ width: `${bufferedPercent}%` }}
              />
              {/* Played progress bar */}
              <div
                className="absolute left-0 top-0 h-full bg-blue-500 rounded-full transition-all duration-75"
                style={{ width: `${playedPercent}%` }}
              />
            </div>
            {/* Scrubber thumb handle */}
            <div
              className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 bg-white rounded-full shadow-lg transition-transform pointer-events-none ${
                isScrubbing ? "scale-125 bg-blue-400" : "scale-0 group-hover:scale-100"
              }`}
              style={{ left: `${playedPercent}%` }}
            />
          </div>
        </div>

        {/* Playback Controls Row */}
        <div className="flex items-center justify-between text-white">
          {/* Left Controls: Play, Rewind 10s, Forward 10s, Time, Volume */}
          <div className="flex items-center space-x-1 sm:space-x-2">
            {/* Play/Pause Button */}
            <button
              onClick={togglePlay}
              className="p-2 sm:p-2.5 rounded-full hover:bg-white/10 text-white transition-transform active:scale-90 focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[40px] min-h-[40px] flex items-center justify-center"
              title={isPlaying ? "Pause (Space/k)" : "Play (Space/k)"}
              aria-label={isPlaying ? "Pause" : "Play"}
            >
              {isPlaying ? (
                <Pause className="w-5 h-5 sm:w-6 sm:h-6 fill-current" />
              ) : (
                <Play className="w-5 h-5 sm:w-6 sm:h-6 fill-current ml-0.5" />
              )}
            </button>

            {/* Rewind 10s */}
            <button
              onClick={() => seekRelative(-10)}
              className="p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors relative focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[36px] min-h-[36px] flex items-center justify-center"
              title="Rewind 10 seconds (Left Arrow/j)"
              aria-label="Rewind 10 seconds"
            >
              <RotateCcw className="w-5 h-5" />
              <span className="absolute text-[8px] font-bold top-2 left-2">10</span>
            </button>

            {/* Forward 10s */}
            <button
              onClick={() => seekRelative(10)}
              className="p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors relative focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[36px] min-h-[36px] flex items-center justify-center"
              title="Forward 10 seconds (Right Arrow/l)"
              aria-label="Forward 10 seconds"
            >
              <RotateCw className="w-5 h-5" />
              <span className="absolute text-[8px] font-bold top-2 left-2">10</span>
            </button>

            {/* Time Indicator */}
            <div className="text-xs sm:text-sm font-mono text-white/85 tracking-tight px-1 select-none tabular-nums">
              <span>{formatTime(currentTime)}</span>
              <span className="text-white/40 mx-1">/</span>
              <span>{formatTime(duration)}</span>
            </div>

            {/* Volume Control (desktop / tablet) */}
            <div className="hidden sm:flex items-center space-x-1 pl-2">
              <button
                onClick={toggleMute}
                className="p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40"
                title={isMuted ? "Unmute (m)" : "Mute (m)"}
                aria-label={isMuted ? "Unmute" : "Mute"}
              >
                {isMuted || volume === 0 ? (
                  <VolumeX className="w-5 h-5" />
                ) : volume < 0.5 ? (
                  <Volume1 className="w-5 h-5" />
                ) : (
                  <Volume2 className="w-5 h-5" />
                )}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={isMuted ? 0 : volume}
                onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
                className="w-16 sm:w-20 h-1 accent-blue-500 bg-white/20 rounded-full cursor-pointer transition-all"
                aria-label="Volume slider"
              />
            </div>
          </div>

          {/* Right Controls: Subtitles, Settings, PiP, Fullscreen */}
          <div className="flex items-center space-x-1 sm:space-x-2 relative">
            {/* Subtitles / CC Toggle */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                setActiveMenu((prev) => (prev === "subtitles" ? "none" : "subtitles"));
                showControls(5000);
              }}
              className={`p-2 sm:p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[36px] min-h-[36px] flex items-center justify-center ${
                activeMenu === "subtitles" ? "bg-white/20 text-white" : ""
              }`}
              title="Subtitles / CC"
              aria-label="Subtitles / CC"
            >
              <Captions className="w-5 h-5" />
            </button>

            {/* Settings Gear */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                setActiveMenu((prev) => (prev === "settings" ? "none" : "settings"));
                showControls(5000);
              }}
              className={`p-2 sm:p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[36px] min-h-[36px] flex items-center justify-center ${
                activeMenu === "settings" ? "bg-white/20 text-white" : ""
              }`}
              title="Settings"
              aria-label="Settings"
            >
              <Settings className="w-5 h-5" />
            </button>

            {/* Picture-in-Picture (hidden on mobile small screens) */}
            {canPiP && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  togglePiP();
                }}
                className={`hidden sm:inline-flex p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation ${
                  isPiPActive ? "bg-blue-600 text-white" : ""
                }`}
                title="Picture-in-Picture"
                aria-label="Picture-in-Picture"
              >
                <PictureInPicture2 className="w-5 h-5" />
              </button>
            )}

            {/* Fullscreen Button */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleFullscreen();
              }}
              className="p-2 sm:p-2 rounded-full hover:bg-white/10 text-white/85 hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-white/40 touch-manipulation min-w-[36px] min-h-[36px] flex items-center justify-center"
              title={isFullscreen ? "Exit Fullscreen (f/Esc)" : "Fullscreen (f)"}
              aria-label={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            >
              {isFullscreen ? <Minimize className="w-5 h-5" /> : <Maximize className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* ================================================================= */}
      {/* Settings Popover (Desktop) & Bottom Sheet (Mobile)                */}
      {/* ================================================================= */}
      {activeMenu !== "none" && activeMenu !== "info" && (
        <>
          {/* Backdrop on mobile */}
          <div
            onClick={(e) => {
              e.stopPropagation();
              setActiveMenu("none");
              showControls(4500);
            }}
            className="fixed inset-0 bg-black/60 backdrop-blur-xs z-40 sm:hidden"
          />

          <div
            onClick={(e) => e.stopPropagation()}
            className="z-50 text-white bg-zinc-900/98 backdrop-blur-xl border border-white/10 shadow-2xl transition-all duration-200 fixed inset-x-0 bottom-0 rounded-t-2xl max-h-[85vh] p-4 sm:absolute sm:inset-auto sm:bottom-20 sm:right-6 sm:w-72 sm:rounded-2xl sm:p-2.5 sm:max-h-[60vh] overflow-y-auto animate-in slide-in-from-bottom duration-200 sm:animate-in sm:fade-in sm:zoom-in-95"
          >
            {/* Main Menu View */}
            {activeMenu === "settings" && (
              <div className="space-y-1">
                <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-white/40 border-b border-white/10 flex items-center justify-between">
                  <span>Player Settings</span>
                  <button
                    onClick={() => {
                      setActiveMenu("none");
                      showControls(4500);
                    }}
                    className="p-1 rounded-full hover:bg-white/10 text-white/60 hover:text-white"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <button
                  onClick={() => setActiveMenu("speed")}
                  className="w-full flex items-center justify-between px-3 py-3 sm:py-2.5 rounded-xl hover:bg-white/10 text-sm transition-colors touch-manipulation"
                >
                  <span className="flex items-center space-x-2.5">
                    <SlidersHorizontal className="w-4 h-4 text-white/70" />
                    <span>Playback speed</span>
                  </span>
                  <div className="flex items-center space-x-1.5 text-white/60 text-xs">
                    <span>{playbackRate === 1 ? "Normal" : `${playbackRate}x`}</span>
                    <ChevronRight className="w-4 h-4" />
                  </div>
                </button>

                <button
                  onClick={() => setActiveMenu("quality")}
                  className="w-full flex items-center justify-between px-3 py-3 sm:py-2.5 rounded-xl hover:bg-white/10 text-sm transition-colors touch-manipulation"
                >
                  <span className="flex items-center space-x-2.5">
                    <Settings className="w-4 h-4 text-white/70" />
                    <span>Quality</span>
                  </span>
                  <div className="flex items-center space-x-1.5 text-white/60 text-xs">
                    <span>Auto (Original)</span>
                    <ChevronRight className="w-4 h-4" />
                  </div>
                </button>

                <button
                  onClick={() => setActiveMenu("subtitles")}
                  className="w-full flex items-center justify-between px-3 py-3 sm:py-2.5 rounded-xl hover:bg-white/10 text-sm transition-colors touch-manipulation"
                >
                  <span className="flex items-center space-x-2.5">
                    <Captions className="w-4 h-4 text-white/70" />
                    <span>Subtitles / CC</span>
                  </span>
                  <div className="flex items-center space-x-1.5 text-white/60 text-xs">
                    <span>Off</span>
                    <ChevronRight className="w-4 h-4" />
                  </div>
                </button>

                <button
                  onClick={() => setActiveMenu("chapters")}
                  className="w-full flex items-center justify-between px-3 py-3 sm:py-2.5 rounded-xl hover:bg-white/10 text-sm transition-colors touch-manipulation"
                >
                  <span className="flex items-center space-x-2.5">
                    <List className="w-4 h-4 text-white/70" />
                    <span>Chapters</span>
                  </span>
                  <div className="flex items-center space-x-1.5 text-white/60 text-xs">
                    <span>None</span>
                    <ChevronRight className="w-4 h-4" />
                  </div>
                </button>

                <button
                  onClick={() => setActiveMenu("transcript")}
                  className="w-full flex items-center justify-between px-3 py-3 sm:py-2.5 rounded-xl hover:bg-white/10 text-sm transition-colors touch-manipulation"
                >
                  <span className="flex items-center space-x-2.5">
                    <FileText className="w-4 h-4 text-white/70" />
                    <span>Transcript</span>
                  </span>
                  <div className="flex items-center space-x-1.5 text-white/60 text-xs">
                    <span>View</span>
                    <ChevronRight className="w-4 h-4" />
                  </div>
                </button>
              </div>
            )}

            {/* Playback Speed Submenu */}
            {activeMenu === "speed" && (
              <div className="space-y-1">
                <div className="flex items-center space-x-2 px-2 py-2 border-b border-white/10 text-sm font-medium">
                  <button
                    onClick={() => setActiveMenu("settings")}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                  <span>Playback Speed</span>
                </div>
                <div className="py-1 max-h-64 overflow-y-auto space-y-0.5">
                  {PLAYBACK_RATES.map((rate) => (
                    <button
                      key={rate}
                      onClick={() => {
                        handlePlaybackRateChange(rate);
                        setActiveMenu("settings");
                      }}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-colors touch-manipulation ${
                        playbackRate === rate
                          ? "bg-blue-600/25 text-blue-400 font-medium"
                          : "hover:bg-white/10 text-white/80"
                      }`}
                    >
                      <span>{rate === 1 ? "1x (Normal)" : `${rate}x`}</span>
                      {playbackRate === rate && <Check className="w-4 h-4 text-blue-400" />}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Quality Submenu */}
            {activeMenu === "quality" && (
              <div className="space-y-2">
                <div className="flex items-center space-x-2 px-2 py-2 border-b border-white/10 text-sm font-medium">
                  <button
                    onClick={() => setActiveMenu("settings")}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                  <span>Video Quality</span>
                </div>
                <div className="px-3 py-2">
                  <div className="flex items-center justify-between py-2 text-sm text-blue-400 font-medium bg-blue-600/20 px-3 rounded-lg border border-blue-500/30">
                    <span>Auto (Original Source)</span>
                    <Check className="w-4 h-4" />
                  </div>
                  <p className="text-[11px] text-white/50 leading-relaxed mt-2.5">
                    Streaming original file directly from Telegram storage without lossy compression. Multi-resolution ladder (1080p, 720p, 480p) requires server-side transcode pipeline.
                  </p>
                </div>
              </div>
            )}

            {/* Subtitles Submenu */}
            {activeMenu === "subtitles" && (
              <div className="space-y-2">
                <div className="flex items-center space-x-2 px-2 py-2 border-b border-white/10 text-sm font-medium">
                  <button
                    onClick={() => setActiveMenu("settings")}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                  <span>Subtitles / CC</span>
                </div>
                <div className="px-3 py-2">
                  <div className="flex items-center justify-between py-2 text-sm text-blue-400 font-medium bg-blue-600/20 px-3 rounded-lg border border-blue-500/30">
                    <span>Off</span>
                    <Check className="w-4 h-4" />
                  </div>
                  <p className="text-[11px] text-white/50 leading-relaxed mt-2.5">
                    No embedded or external subtitle tracks (.vtt / .srt) were detected for this media file.
                  </p>
                </div>
              </div>
            )}

            {/* Chapters Submenu */}
            {activeMenu === "chapters" && (
              <div className="space-y-2">
                <div className="flex items-center space-x-2 px-2 py-2 border-b border-white/10 text-sm font-medium">
                  <button
                    onClick={() => setActiveMenu("settings")}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                  <span>Chapters</span>
                </div>
                <div className="px-3 py-6 text-center text-white/50 text-xs">
                  <List className="w-8 h-8 mx-auto mb-2 text-white/30" />
                  <p>No chapter markers found in this video stream.</p>
                </div>
              </div>
            )}

            {/* Transcript Submenu */}
            {activeMenu === "transcript" && (
              <div className="space-y-2">
                <div className="flex items-center space-x-2 px-2 py-2 border-b border-white/10 text-sm font-medium">
                  <button
                    onClick={() => setActiveMenu("settings")}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/70 hover:text-white"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                  <span>Transcript</span>
                </div>
                <div className="px-2 pt-1">
                  <div className="relative mb-3">
                    <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-white/40" />
                    <input
                      type="text"
                      placeholder="Search transcript..."
                      value={transcriptSearch}
                      onChange={(e) => setTranscriptSearch(e.target.value)}
                      className="w-full pl-8 pr-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-white placeholder-white/40 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                  <div className="p-4 text-center text-white/50 text-xs bg-white/5 rounded-xl border border-white/10">
                    <FileText className="w-8 h-8 mx-auto mb-2 text-white/30" />
                    <p className="font-medium text-white/70 mb-1">Transcript unavailable</p>
                    <p className="text-[11px] text-white/40 leading-relaxed">
                      Speech-to-text transcript generation requires backend Whisper/AI integration.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* ================================================================= */}
      {/* File Details / Info Modal                                         */}
      {/* ================================================================= */}
      {activeMenu === "info" && (
        <div
          onClick={() => {
            setActiveMenu("none");
            showControls(4500);
          }}
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-200"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md bg-zinc-900 border border-white/10 rounded-2xl shadow-2xl p-5 text-white animate-in zoom-in-95 duration-150"
          >
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <div className="flex items-center space-x-2">
                <Info className="w-5 h-5 text-blue-400" />
                <h3 className="text-base font-semibold">Media Details</h3>
              </div>
              <button
                onClick={() => {
                  setActiveMenu("none");
                  showControls(4500);
                }}
                className="p-1 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="py-4 space-y-3 text-sm">
              <div className="flex items-start justify-between">
                <span className="text-white/50 text-xs">File Name</span>
                <span className="text-right font-medium max-w-[240px] truncate text-white/95">
                  {fileName}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-white/50 text-xs">Format / Container</span>
                <span className="font-mono text-xs px-2 py-0.5 rounded bg-white/10 text-white/90">
                  {fileExt}
                </span>
              </div>
              {videoDimensions && (
                <div className="flex items-center justify-between">
                  <span className="text-white/50 text-xs">Resolution</span>
                  <span className="font-mono text-xs text-white/90">
                    {videoDimensions.width} × {videoDimensions.height}
                  </span>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-white/50 text-xs">Total Duration</span>
                <span className="font-mono text-xs text-white/90">{formatTime(duration)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-white/50 text-xs">Streaming Mode</span>
                <span className="text-xs text-emerald-400 font-medium">
                  HTTP/1.1 Range Requests
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-white/10 flex justify-end">
              <button
                onClick={() => {
                  setActiveMenu("none");
                  showControls(4500);
                }}
                className="px-4 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs font-medium text-white transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* External Player Menu Dialog (Opened via top bar button only) */}
      {activeMenu === "external" && (
        <div 
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-200 pointer-events-auto"
          onClick={() => setActiveMenu("none")}
        >
          <div 
            className="w-full max-w-sm bg-zinc-900 border border-white/15 rounded-2xl p-5 shadow-2xl space-y-4 pointer-events-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <div className="flex items-center space-x-2">
                <ExternalLink className="w-5 h-5 text-blue-400" />
                <h3 className="font-semibold text-white text-sm sm:text-base">Open in External Player</h3>
              </div>
              <button 
                onClick={() => setActiveMenu("none")}
                className="p-1 rounded-full text-white/50 hover:text-white hover:bg-white/10"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-white/70 leading-relaxed">
              Play this video directly in an external app installed on your device:
            </p>

            <div className="space-y-2.5">
              {/* VLC Button */}
              <a
                href={`vlc://${fullMediaUrl}`}
                target="_blank"
                rel="noreferrer"
                className="w-full flex items-center justify-between py-2.5 px-4 rounded-xl bg-orange-600 hover:bg-orange-500 active:bg-orange-700 text-white font-medium text-xs sm:text-sm transition-colors shadow-sm cursor-pointer"
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-base">🟠</span>
                  <span>VLC Media Player</span>
                </div>
                <ExternalLink className="w-4 h-4 opacity-80" />
              </a>

              {/* MX Player / External App Intent */}
              <a
                href={`intent:${fullMediaUrl}#Intent;type=video/*;end`}
                className="w-full flex items-center justify-between py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-medium text-xs sm:text-sm transition-colors shadow-sm cursor-pointer"
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-base">📱</span>
                  <span>MX Player / Mobile App</span>
                </div>
                <ExternalLink className="w-4 h-4 opacity-80" />
              </a>

              {/* Copy Stream Link */}
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(fullMediaUrl);
                  toast.success("Stream link copied to clipboard!");
                  setActiveMenu("none");
                }}
                className="w-full flex items-center justify-between py-2.5 px-4 rounded-xl bg-white/10 hover:bg-white/20 active:bg-white/30 text-white font-medium text-xs sm:text-sm transition-colors border border-white/15 cursor-pointer"
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-base">📋</span>
                  <span>Copy Stream URL</span>
                </div>
                <Check className="w-4 h-4 opacity-80" />
              </button>
            </div>

            <div className="pt-2 border-t border-white/10 flex justify-end">
              <button
                onClick={() => {
                  setActiveMenu("none");
                  showControls(4500);
                }}
                className="px-4 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs font-medium text-white transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};