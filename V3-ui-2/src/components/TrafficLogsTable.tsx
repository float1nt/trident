import { Spin, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { RefObject } from "react";
import type { RiskTrafficLogItem } from "@/api/services/RiskService";
import { formatTrafficVolumeText } from "@/utils/formatTotalTraffic";

const LIST_MAX_HEIGHT = "200px";

function formatPort(port: number): string {
  return port > 0 ? String(port) : "-";
}

const trafficLogColumns: ColumnsType<RiskTrafficLogItem> = [
  {
    title: "源IP",
    dataIndex: "srcIp",
    key: "srcIp",
    width: 140,
  },
  {
    title: "源端口",
    dataIndex: "srcPort",
    key: "srcPort",
    width: 90,
    align: "center",
    render: (port: number) => formatPort(port),
  },
  {
    title: "目的IP",
    dataIndex: "dstIp",
    key: "dstIp",
    width: 140,
  },
  {
    title: "目的端口",
    dataIndex: "dstPort",
    key: "dstPort",
    width: 90,
    align: "center",
    render: (port: number) => formatPort(port),
  },
  {
    title: "访问时间",
    dataIndex: "accessTime",
    key: "accessTime",
    width: 180,
  },
  {
    title: "流量",
    dataIndex: "traffic",
    key: "traffic",
    width: 110,
    align: "right",
    render: (bytes: number) => formatTrafficVolumeText(bytes),
  },
  {
    title: "协议类型",
    dataIndex: "protocol",
    key: "protocol",
    width: 120,
  },
];

type TrafficLogsTableProps = {
  trafficLogs: RiskTrafficLogItem[];
  loading: boolean;
  hasMore: boolean;
  tableWrapperRef: RefObject<HTMLDivElement>;
};

export function TrafficLogsTable({
  trafficLogs,
  loading,
  hasMore,
  tableWrapperRef,
}: TrafficLogsTableProps) {
  return (
    <div ref={tableWrapperRef}>
      <Table<RiskTrafficLogItem>
        rowKey="id"
        size="middle"
        bordered
        columns={trafficLogColumns}
        dataSource={trafficLogs}
        pagination={false}
        scroll={{ x: 980, y: LIST_MAX_HEIGHT }}
        footer={() => {
          if (loading) {
            return (
              <div className="py-2 text-center">
                <Spin size="small" />
              </div>
            );
          }
          if (!hasMore && trafficLogs.length > 0) {
            return (
              <div className="py-2 text-center text-sm text-[#8c8c8c]">
                已加载全部
              </div>
            );
          }
          return null;
        }}
      />
    </div>
  );
}
