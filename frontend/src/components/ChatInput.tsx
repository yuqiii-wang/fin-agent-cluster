import { useState } from "react";
import { Flex, Input, Button, theme } from "antd";
import { SendOutlined, StopOutlined } from "@ant-design/icons";

interface Props {
  onSubmit: (query: string) => void;
  onCancel?: () => void;
  loading: boolean;
}

export function ChatInput({ onSubmit, onCancel, loading }: Props) {
  const { token } = theme.useToken();
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
      style={{
        padding: "12px 16px",
        background: token.colorBgContainer,
        borderTop: `1px solid ${token.colorBorder}`,
      }}
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
