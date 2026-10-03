import { useEffect, useRef, useState } from "react";

// Shows the part of a sheet image that holds one question's bubbles.
//
// `crop` is in the coordinates of the aligned image (the template's page
// size); the picture is scaled to match, whatever its real pixel size.
// Without a crop (or if the image cannot be shown) the whole sheet is
// shown instead, so a reviewer can always see something. The image comes
// from an authorized API route; no file path is ever involved.

const SHOW_WIDTH = 520;

export default function OmrCrop({ src, fullSrc, crop, label }) {
  const canvasRef = useRef(null);
  const [failed, setFailed] = useState(false);
  const [full, setFull] = useState(!crop);

  useEffect(() => {
    if (!crop || !src || full) return undefined;

    let cancelled = false;
    const image = new Image();

    image.onload = () => {
      if (cancelled || !canvasRef.current) return;

      const scale = image.naturalWidth / crop.page_width;
      const canvas = canvasRef.current;
      const ratio = SHOW_WIDTH / (crop.width * scale);

      canvas.width = SHOW_WIDTH;
      canvas.height = Math.max(1, Math.round(crop.height * scale * ratio));

      canvas
        .getContext("2d")
        .drawImage(
          image,
          crop.x * scale,
          crop.y * scale,
          crop.width * scale,
          crop.height * scale,
          0,
          0,
          canvas.width,
          canvas.height
        );
    };
    image.onerror = () => !cancelled && setFailed(true);
    image.src = src;

    return () => {
      cancelled = true;
    };
  }, [src, crop, full]);

  if (!src && !fullSrc) {
    return <div className="omr-no-image">The image is no longer available.</div>;
  }

  if (full || failed || !crop) {
    return (
      <div className="omr-image-full">
        <div className="import-hint">
          Full sheet — look for {label}. Open the image to zoom.
        </div>
        <a href={fullSrc || src} rel="noreferrer" target="_blank">
          <img alt={`Sheet, ${label}`} src={fullSrc || src} />
        </a>
        {crop && !failed && (
          <button className="link-button" onClick={() => setFull(false)} type="button">
            Show only {label}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="omr-image-crop">
      <canvas aria-label={`Answer region, ${label}`} ref={canvasRef} />
      <button className="link-button" onClick={() => setFull(true)} type="button">
        Show full sheet
      </button>
    </div>
  );
}
