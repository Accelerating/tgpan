import { t } from "../i18n";
import { useData } from "../lib/hooks";
import { folderPath } from "../lib/folders";
import type { FolderItem } from "../lib/types";
import { ErrorBanner } from "./Shared";

export default function FolderSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const { data, error } = useData<FolderItem[]>("/files/folders");
  return (
    <label className="field-label">
      {t("目标目录")}
      <select
        className="native-select"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{t("/ 全部文件")}</option>
        {(data || []).map((folder) => (
          <option key={folder.id} value={folder.id}>
            {folderPath(folder, data || [])}
          </option>
        ))}
      </select>
      <ErrorBanner message={error} />
    </label>
  );
}
