import { t } from "../i18n";
import TaskPage, { type TaskPageProps } from "../components/downloads/TaskPage";
import CreateTask from "../components/offline/CreateTask";
import SelectFiles from "../components/offline/SelectFiles";
export default function Offline(props: TaskPageProps) {
  return (
    <TaskPage
      {...props}
      base="/offline"
      title={t("离线下载")}
      emptyTitle={t("暂无离线下载")}
      unavailableMessage={t("请先联系管理员在设置中安装 aria2")}
      selectLabel={t("选择下载文件")}
      renderCreate={(p) => (
        <CreateTask {...p} onCreated={(tasks) => p.onCreated(tasks)} />
      )}
      renderSelection={(p) => <SelectFiles {...p} />}
    />
  );
}
