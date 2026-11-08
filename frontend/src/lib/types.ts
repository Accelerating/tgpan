export interface User {
  id: string;
  username: string;
  admin: number;
  disabled: number;
  created_at: number;
}
export interface Node {
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
