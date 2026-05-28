import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { sharedPaginationProps } from "./constants/tablePagination";
import "antd/dist/reset.css";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      pagination={sharedPaginationProps}
      theme={{
        components: {
          Table: {
            headerBg: "#f0f5ff",
            headerSortActiveBg: "#e6f0ff",
            headerSortHoverBg: "#e8f3ff",
          },
        },
      }}
    >
      <RouterProvider
        router={router}
        future={{
          v7_startTransition: true,
        }}
      />
    </ConfigProvider>
  </React.StrictMode>
);
