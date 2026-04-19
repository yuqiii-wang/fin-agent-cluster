import { Dropdown, Flex, Space, Tooltip, Typography } from "antd";
import { DownOutlined, LoadingOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import { useState } from "react";
import type { TaskInfo } from "../../types";
import { cancelTask, passTask } from "../../api";

const ACTIONS_HELP = (
  <div style={{ maxWidth: 260 }}>
    <p style={{ margin: "0 0 6px" }}>
      <strong>Cancel</strong> — stops the LLM stream immediately and marks this task as
      <em> cancelled</em>. Downstream tasks that depend on its output will be skipped.
    </p>
    <p style={{ margin: 0 }}>
      <strong>Pass</strong> — stops the stream and accepts whatever the LLM has generated so
      far as the final output. The partial JSON is used to populate the required output schema.
    </p>
  </div>
);

export function LlmTaskActions({ task }: { task: TaskInfo }) {
  const [busy, setBusy] = useState(false);

  const handleAction = async (action: "cancel" | "pass") => {
    setBusy(true);
    try {
      if (action === "cancel") {
        await cancelTask(task.id);
      } else {
        await passTask(task.id);
      }
    } catch (err) {
      console.error("[LlmTaskActions] action failed", err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Flex align="center" gap={6}>
      <Dropdown
        disabled={busy}
        menu={{
          items: [
            { key: "cancel", label: "Cancel", danger: true, onClick: () => handleAction("cancel") },
            { key: "pass",   label: "Pass",                  onClick: () => handleAction("pass")   },
          ],
        }}
        trigger={["click"]}
      >
        <a onClick={(e) => e.preventDefault()} style={{ fontSize: 11, userSelect: "none" }}>
          <Space size={4}>
            {busy ? <LoadingOutlined style={{ fontSize: 11 }} /> : null}
            Actions
            <DownOutlined style={{ fontSize: 9 }} />
          </Space>
        </a>
      </Dropdown>
      <Tooltip title={ACTIONS_HELP} placement="rightTop">
        <QuestionCircleOutlined style={{ fontSize: 12, color: "var(--ant-color-text-quaternary)", cursor: "help" }} />
      </Tooltip>
    </Flex>
  );
}
