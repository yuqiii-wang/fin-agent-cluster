import { Button, Flex, Tooltip, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { useState } from "react";
import type { TaskInfo } from "../../types";
import { passTask } from "../../api";
import { styles } from "./LlmTaskActions.styles";

const PASS_HELP = (
  <div style={styles.tooltipContent}>
    <p style={styles.tooltipParagraph}>
      <strong>Pass</strong> — stops the LLM stream and accepts whatever has been
      generated so far as the final output. The partial JSON populates the required
      output schema.
    </p>
  </div>
);

export function LlmTaskActions({ task }: { task: TaskInfo }) {
  const [busy, setBusy] = useState(false);

  const handlePass = async () => {
    setBusy(true);
    try {
      await passTask(task.id);
    } catch (err) {
      console.error("[LlmTaskActions] pass failed", err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Flex align="center" gap={6}>
      <Tooltip title={PASS_HELP} placement="rightTop">
        <Button
          size="small"
          onClick={handlePass}
          disabled={busy}
          icon={busy ? <LoadingOutlined style={styles.loadingIcon} /> : undefined}
          style={styles.button}
        >
          Pass
        </Button>
      </Tooltip>
    </Flex>
  );
}
