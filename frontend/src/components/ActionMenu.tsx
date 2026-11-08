import { t } from "../i18n";
import type { ReactNode } from "react";
import {
  Button,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/react";
import { MoreHorizontal } from "lucide-react";
export type MenuAction = {
  key: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  onPress: () => void;
};
export default function ActionMenu({
  label,
  actions,
}: {
  label: string;
  actions: MenuAction[];
}) {
  return (
    <div className="action-menu">
      <div className="action-menu-inline">
        {actions.map((action) => (
          <Button
            key={action.key}
            isIconOnly
            size="sm"
            variant="light"
            aria-label={`${action.label} ${label}`}
            isDisabled={action.disabled}
            onPress={action.onPress}
          >
            {action.icon}
          </Button>
        ))}
      </div>
      <div className="action-menu-overflow">
        <Dropdown placement="bottom-end">
          <DropdownTrigger>
            <Button
              isIconOnly
              variant="light"
              aria-label={t("更多操作 {p0}", { p0: label })}
            >
              <MoreHorizontal size={20} />
            </Button>
          </DropdownTrigger>
          <DropdownMenu
            aria-label={t("{p0} 的操作", { p0: label })}
            items={actions}
            disabledKeys={actions
              .filter((action) => action.disabled)
              .map((action) => action.key)}
            onAction={(key) =>
              actions.find((action) => action.key === key)?.onPress()
            }
          >
            {(action) => (
              <DropdownItem
                key={action.key}
                startContent={action.icon}
                className="min-h-10"
              >
                {action.label}
              </DropdownItem>
            )}
          </DropdownMenu>
        </Dropdown>
      </div>
    </div>
  );
}
