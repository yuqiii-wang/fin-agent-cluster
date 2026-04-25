import { useState } from "react";
import { Flex, Input, Button } from "antd";
import { SendOutlined, StopOutlined } from "@ant-design/icons";
import { useStyles } from "./ChatInput.styles";

interface Props {
  onSubmit: (query: string) => void;
  onCancel?: () => void;
  loading: boolean;
}

export function ChatInput({ onSubmit, onCancel, loading }: Props) {
  const styles = useStyles();
  const [value, setValue] = useState("");

  const handleSend = () => {
    const q = value.trim();
    if (!q || loading) return;
    setValue("");
    onSubmit(q);
  };

  return (
    <Flex
      gap={8}
      style={styles.inputBar}
    >
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onPressEnter={handleSend}
        placeholder="Ask about any ticker, e.g. Should I buy AAPL?"
        size="large"
        disabled={loading}
        autoFocus
      />
      {loading ? (
        <Button
          danger
          size="large"
          icon={<StopOutlined />}
          onClick={onCancel}
        >
          Cancel
        </Button>
      ) : (
        <Button
          type="primary"
          size="large"
          icon={<SendOutlined />}
          onClick={handleSend}
          loading={loading}
          disabled={!value.trim()}
        >
          Send
        </Button>
      )}
    </Flex>
  );
}
