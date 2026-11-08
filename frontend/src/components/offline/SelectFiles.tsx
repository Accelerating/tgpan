import { useState } from "react";
import { Checkbox, Button } from "@heroui/react";
import { t } from "../../i18n";
import { api, errorText, formatSize } from "../../lib/api";
import type { OfflineTask } from "../../lib/types";
import { AlertDialog, Dialog } from "../Shared";

export default function SelectFiles({
  task,
  onClose,
  onSelected,
  maxFileSize,
}: {
  task: OfflineTask;
  onClose: () => void;
  onSelected: () => void;
  maxFileSize: number;
}) {
  const [selected, setSelected] = useState(
    task.files.map((file) => file.position),
  );
  const [failure, setFailure] = useState("");
  const total = task.files
    .filter((file) => selected.includes(file.position))
    .reduce((sum, file) => sum + file.size, 0);
  return (
    <>
      <Dialog
        title={t("选择下载文件")}
        confirmLabel={t("开始下载")}
        onClose={onClose}
        onConfirm={async () => {
          try {
            await api(`/offline/${task.id}/select`, "POST", {
              positions: selected,
            });
            onSelected();
          } catch (error) {
            setFailure(errorText(error));
            throw error;
          }
        }}
      >
        <p>{task.name}</p>
        <div className="offline-selection-tools">
          <Button
            size="sm"
            variant="light"
            onPress={() => setSelected(task.files.map((file) => file.position))}
          >
            {t("全选")}
          </Button>
          <Button size="sm" variant="light" onPress={() => setSelected([])}>
            {t("取消全选")}
          </Button>
          <span className="muted">{formatSize(total)}</span>
        </div>
        <div className="offline-file-selection">
          {task.files.map((file) => (
            <div className="offline-file-choice" key={file.id}>
              <Checkbox
                isSelected={selected.includes(file.position)}
                onValueChange={(checked) =>
                  setSelected((old) =>
                    checked
                      ? [...old, file.position]
                      : old.filter((index) => index !== file.position),
                  )
                }
              >
                <span className="offline-file-path">{file.path}</span>
              </Checkbox>
              <small
                className={file.size > maxFileSize ? "inline-error" : "muted"}
              >
                {formatSize(file.size)}
                {file.size > maxFileSize && ` · ${t("超出单文件上限")}`}
              </small>
            </div>
          ))}
        </div>
      </Dialog>
      {failure && (
        <AlertDialog title={t("无法开始下载")} onClose={() => setFailure("")}>
          <p>{failure}</p>
        </AlertDialog>
      )}
    </>
  );
}
