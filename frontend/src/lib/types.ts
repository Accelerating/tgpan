export interface User {
  id: string;
  username: string;
  admin: number;
  disabled: number;
  created_at: number;
}
export interface Node {
  has_video_metadata?: boolean;
  id: string;
  name: string;
  kind: "file" | "folder";
  size: number;
  parent_id: string | null;
  status: string;
  updated_at: number;
  deleted_at: number | null;
  preview_kind: "image" | "video" | null;
}
export interface Listing {
  items: Node[];
  breadcrumbs: { id: string; name: string }[];
}
export interface StorageConfig {
  id: string;
  name: string;
  channel: string;
  is_default: number;
  created_at: number;
}
export interface Upload {
  id: string;
  node_id: string;
  name: string;
  size: number;
  received: number;
  stored: number;
  sending_bytes: number;
  state: string;
  error: string | null;
  parent_id: string | null;
  config_id: string;
  fingerprint: string;
}
export interface Transfers {
  uploads: Upload[];
  cleanup: { id: string; state: string; error: string | null }[];
}
export interface System {
  max_file_size: number;
  chunk_size: number;
  block_size: number;
  storage_backend: "bot_api";
}
export type Notify = (message: string, error?: boolean) => void;

export interface FolderItem {
  id: string;
  name: string;
  parent_id: string | null;
}
export interface OfflineFile {
  id: string;
  position: number;
  path: string;
  size: number;
  selected: number;
  complete: number;
  node_id: string | null;
  stored: number;
}
export interface OfflineTask {
  id: string;
  name: string;
  kind: string;
  state: string;
  phase: string;
  parent_id: string | null;
  total: number;
  downloaded: number;
  stored: number;
  download_speed: number;
  store_speed: number;
  error: string | null;
  updated_at: number;
  files: OfflineFile[];
}
export interface OfflineSettings {
  concurrency: number;
  max_bytes: number;
  reserve_bytes: number;
  max_file_size: number;
  available: boolean;
  free_bytes: number;
}
export interface Aria2Info {
  installed: boolean;
  version: string | null;
  path: string | null;
  managed: boolean;
  platform: string;
  state: string;
  error: string | null;
  message: string;
}

export interface Share {
  id: string;
  node_id: string;
  name: string;
  title: string;
  path: string;
  has_password: boolean;
  status: "active" | "expired" | "revoked";
  expires_at: number | null;
  created_at: number;
}
export interface PublicShareInfo {
  title: string;
  requires_password: boolean;
  name?: string;
  kind?: "file" | "folder";
  size?: number;
  preview_kind?: "image" | "video" | null;
  expires_at?: number | null;
}

export type PublicNode = Pick<
  Node,
  "id" | "name" | "kind" | "size" | "updated_at" | "preview_kind"
>;
export interface PublicListing {
  items: PublicNode[];
  breadcrumbs: { id: string; name: string }[];
}
