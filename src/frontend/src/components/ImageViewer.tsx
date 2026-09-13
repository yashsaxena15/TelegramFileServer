import { useState, useEffect } from "react";
import Lightbox from "yet-another-react-lightbox";
import "yet-another-react-lightbox/styles.css";

import Zoom from "yet-another-react-lightbox/plugins/zoom";
import Thumbnails from "yet-another-react-lightbox/plugins/thumbnails";
import "yet-another-react-lightbox/plugins/thumbnails.css";
import Slideshow from "yet-another-react-lightbox/plugins/slideshow";
import Fullscreen from "yet-another-react-lightbox/plugins/fullscreen";
import Download from "yet-another-react-lightbox/plugins/download";
import Counter from "yet-another-react-lightbox/plugins/counter";
import "yet-another-react-lightbox/plugins/counter.css";

export interface ImageSlideItem {
  url: string;
  fileName: string;
}

interface ImageViewerProps {
  imageUrl?: string;
  fileName?: string;
  images?: ImageSlideItem[];
  initialIndex?: number;
  onClose: () => void;
}

export const ImageViewer = ({
  imageUrl,
  fileName,
  images,
  initialIndex = 0,
  onClose
}: ImageViewerProps) => {
  // Construct slides list
  const slides = (images && images.length > 0)
    ? images.map(img => ({
        src: img.url,
        title: img.fileName,
        download: `${img.url}&download=1`,
      }))
    : imageUrl
      ? [{ src: imageUrl, title: fileName || "Image", download: `${imageUrl}&download=1` }]
      : [];

  const [index, setIndex] = useState(initialIndex);

  useEffect(() => {
    setIndex(initialIndex);
  }, [initialIndex]);

  if (slides.length === 0) return null;

  return (
    <Lightbox
      open={true}
      close={onClose}
      index={index}
      slides={slides}
      on={{
        view: ({ index: newIndex }) => setIndex(newIndex),
      }}
      plugins={[Zoom, Thumbnails, Slideshow, Fullscreen, Download, Counter]}
      zoom={{
        maxZoomPixelRatio: 5,
        zoomInMultiplier: 1.5,
        doubleTapDelay: 300,
        doubleClickDelay: 300,
        doubleClickMaxStops: 2,
        keyboardMoveDistance: 50,
        wheelZoomDistanceFactor: 100,
        pinchZoomDistanceFactor: 100,
        scrollToZoom: true,
      }}
      thumbnails={{
        position: "bottom",
        width: 80,
        height: 50,
        border: 2,
        borderRadius: 4,
        padding: 4,
        gap: 8,
        showToggle: true,
      }}
      slideshow={{
        autoplay: false,
        delay: 3000,
      }}
      carousel={{
        finite: false,
        preload: 2,
      }}
      render={{
        buttonPrev: slides.length <= 1 ? () => null : undefined,
        buttonNext: slides.length <= 1 ? () => null : undefined,
      }}
    />
  );
};