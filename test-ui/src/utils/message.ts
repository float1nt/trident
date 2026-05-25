import { message as antdMessage, Modal } from "antd";

// 导出 Ant Design 的 message
export const message = antdMessage;

// 导出 Ant Design 的 Modal 方法作为 messageBox
export const messageBox = {
  confirm: (content: string, title: string = "提示"): Promise<boolean> => {
    return new Promise((resolve) => {
      Modal.confirm({
        title,
        content,
        okText: "确定",
        cancelText: "取消",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  },
  alert: (content: string, title: string = "提示"): Promise<void> => {
    return new Promise((resolve) => {
      Modal.info({
        title,
        content,
        onOk: () => resolve(),
      });
    });
  },
};

