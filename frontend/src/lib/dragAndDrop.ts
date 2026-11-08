import { useState, type DragEvent } from "react";

const ITEM_TYPE = "application/x-pan-items";
export const isFileDrag = (transfer: DataTransfer) =>
  Array.from(transfer.types).includes("Files");

export function useItemDrag(
  enabled: boolean,
  onDrop: (ids: string[], target: string) => void,
) {
  const [ids, setIds] = useState<string[]>([]);
  const [target, setTarget] = useState<string | null>(null);
  const reset = () => {
    setIds([]);
    setTarget(null);
  };
  const isItemDrag = (event: DragEvent) =>
    Array.from(event.dataTransfer.types).includes(ITEM_TYPE);
  return {
    ids,
    target,
    sourceProps: (items: string[]) => ({
      draggable: enabled,
      onDragStart: (event: DragEvent<HTMLElement>) => {
        event.dataTransfer.setData(ITEM_TYPE, JSON.stringify(items));
        event.dataTransfer.effectAllowed = "move";
        setIds(items);
      },
      onDragEnd: reset,
    }),
    targetProps: (key: string, allowed = true) => ({
      onDragOver: (event: DragEvent<HTMLElement>) => {
        if (!isItemDrag(event)) return;
        event.preventDefault();
        event.stopPropagation();
        const valid = enabled && allowed && !ids.includes(key);
        event.dataTransfer.dropEffect = valid ? "move" : "none";
        setTarget(valid ? key : null);
      },
      onDragLeave: (event: DragEvent<HTMLElement>) => {
        if (
          event.relatedTarget instanceof globalThis.Node &&
          event.currentTarget.contains(event.relatedTarget)
        )
          return;
        setTarget((current) => (current === key ? null : current));
      },
      onDrop: (event: DragEvent<HTMLElement>) => {
        if (!isItemDrag(event)) return;
        event.preventDefault();
        event.stopPropagation();
        reset();
        if (!enabled || !allowed) return;
        try {
          const items: unknown = JSON.parse(
            event.dataTransfer.getData(ITEM_TYPE),
          );
          if (
            Array.isArray(items) &&
            items.length > 0 &&
            items.length <= 500 &&
            items.every((id) => typeof id === "string") &&
            !items.includes(key)
          )
            onDrop([...new Set(items)], key);
        } catch {
          // Ignore payloads that do not match our internal item format.
        }
      },
    }),
  };
}
