import { Cloud, FileImage, FileText, Folder, Film } from "lucide-react";
import "./CloudBackdrop.css";

export default function CloudBackdrop() {
  return (
    <div className="cloud-backdrop" aria-hidden="true">
      <div className="cloud-backdrop-grid" />
      <svg
        className="cloud-backdrop-art"
        viewBox="0 0 1440 960"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        <g className="cloud-backdrop-orbits">
          <ellipse
            cx="720"
            cy="480"
            rx="580"
            ry="340"
            transform="rotate(-24 720 480)"
          />
          <ellipse
            cx="720"
            cy="480"
            rx="650"
            ry="410"
            transform="rotate(-24 720 480)"
          />
        </g>
        <g className="cloud-backdrop-links">
          <path d="M220 280v150q0 36 36 36h160M1220 650V460q0-36-36-36h-160" />
          <path d="M365 745h120M1060 185H940" />
          <circle cx="220" cy="280" r="5" />
          <circle cx="1220" cy="650" r="5" />
        </g>
        <Cloud
          x="1080"
          y="90"
          width="240"
          height="160"
          className="cloud-backdrop-cloud cloud-backdrop-cloud-top"
          strokeWidth="0.6"
        />
        <Cloud
          x="100"
          y="690"
          width="270"
          height="180"
          className="cloud-backdrop-cloud cloud-backdrop-cloud-bottom"
          strokeWidth="0.6"
        />
        <g
          className="cloud-backdrop-tile cloud-backdrop-folder"
          transform="translate(174 215) rotate(-12 46 46)"
        >
          <rect width="92" height="92" rx="24" />
          <Folder x="25" y="25" width="42" height="42" strokeWidth="1.2" />
        </g>
        <g
          className="cloud-backdrop-tile cloud-backdrop-image"
          transform="translate(315 640) rotate(10 38 38)"
        >
          <rect width="76" height="76" rx="21" />
          <FileImage x="21" y="21" width="34" height="34" strokeWidth="1.2" />
        </g>
        <g
          className="cloud-backdrop-tile cloud-backdrop-film"
          transform="translate(1178 610) rotate(12 46 46)"
        >
          <rect width="92" height="92" rx="24" />
          <Film x="25" y="25" width="42" height="42" strokeWidth="1.2" />
        </g>
        <g
          className="cloud-backdrop-tile cloud-backdrop-document"
          transform="translate(1020 230) rotate(-8 34 34)"
        >
          <rect width="68" height="68" rx="19" />
          <FileText x="19" y="19" width="30" height="30" strokeWidth="1.2" />
        </g>
      </svg>
    </div>
  );
}
