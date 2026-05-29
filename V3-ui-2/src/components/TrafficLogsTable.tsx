import { useMemo, useState } from "react";
import { Button, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TablePaginationConfig } from "antd/es/table";
import type { RiskTrafficLogItem } from "@/api/services/RiskService";
import { TrafficLogDetailDrawer } from "@/components/TrafficLogDetailDrawer";
import { formatTrafficVolumeText } from "@/utils/formatTotalTraffic";
import { normalizeApiList } from "@/utils/normalizeApiList";

function formatPort(port: number): string {
  return port > 0 ? String(port) : "-";
}

function buildTrafficLogColumns(
  onOpenDetail: (index: number) => void,
): ColumnsType<RiskTrafficLogItem> {
  return [
    {
      title: "访问时间",
      dataIndex: "accessTime",
      key: "accessTime",
      width: 180,
    },
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
      render: (port: number) => formatPort(port),
    },
    {
      title: "协议类型",
      dataIndex: "protocol",
      key: "protocol",
      width: 120,
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
      render: (port: number) => formatPort(port),
    },
    {
      title: "流量",
      dataIndex: "traffic",
      key: "traffic",
      width: 110,
      render: (bytes: number) => formatTrafficVolumeText(bytes),
    },
    {
      title: "操作",
      key: "action",
      width: 88,
      fixed: "right",
      render: (_value, _record, index) => (
        <Button
          type="link"
          className="!h-auto !p-0"
          onClick={() => onOpenDetail(index)}
        >
          详情
        </Button>
      ),
    },
  ];
}

type TrafficLogsTableProps = {
  trafficLogs: RiskTrafficLogItem[];
  loading: boolean;
  pagination: TablePaginationConfig;
};

export function TrafficLogsTable({
  trafficLogs,
  loading,
  pagination,
}: TrafficLogsTableProps) {
  const rows = normalizeApiList<RiskTrafficLogItem>(trafficLogs);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const columns = useMemo(
    () =>
      buildTrafficLogColumns((index) => {
        setActiveIndex(index);
        setDrawerOpen(true);
      }),
    [],
  );

  return (
    <>
      <Table<RiskTrafficLogItem>
        rowKey="id"
        size="middle"
        bordered
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={pagination}
        scroll={{ x: 1068 }}
      />
      <TrafficLogDetailDrawer
        open={drawerOpen}
        logs={rows}
        activeIndex={activeIndex}
        onClose={() => setDrawerOpen(false)}
        onActiveIndexChange={setActiveIndex}
      />
    </>
  );
}
