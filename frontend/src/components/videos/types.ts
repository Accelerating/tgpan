import type { OfflineTask } from "../../lib/types";
export type VideoMetadata = {
  size?: number;
  title: string;
  id?: string;
  uploader?: string;
  channel?: string;
  site?: string;
  upload_date?: string;
  duration?: number;
  description?: string;
  thumbnail?: string;
  webpage_url?: string;
  height?: number;
  width?: number;
  fps?: number;
  vcodec?: string;
  acodec?: string;
  ext?: string;
  format?: string;
  qualities?: number[];
  subtitles?: Record<string, { ext?: string; name?: string }[]>;
};
export type VideoTask = OfflineTask & {
  phase: string;
  options: {
    cookie_id?: string;
    quality: string;
    audio_only: number;
    collection_title: string;
  };
  entries: {
    id: string;
    position: number;
    metadata: VideoMetadata;
    file_id?: string;
    node_id?: string;
  }[];
};
export type VideoCookie = { id: string; name: string; domain: string };
