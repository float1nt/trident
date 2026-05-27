import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Table, Input, Button, Space, Tooltip, Tag, Tabs, DatePicker, Card, Typography } from "antd";
import type { Dayjs } from "dayjs";
import type { ColumnsType } from "antd/es/table";
import type { IpRiskListItem } from "@/api/types";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import { LearnerInternalTopologyPanel } from "@/components/LearnerInternalTopologyPanel";
import { RiskService } from "@/api/services/RiskService";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";
import "./RiskTaskList.css";

type RiskSearchForm = {
  name: string;
  subjectIp: string;
};

const EMPTY_SEARCH: RiskSearchForm = {
  name: "",
  subjectIp: "",
};

type EventSearchForm = {
  name: string;
  triggerPeriod: [Dayjs, Dayjs] | null;
};

const EMPTY_EVENT_SEARCH: EventSearchForm = {
  name: "",
  triggerPeriod: null,
};

type RiskViewTab = "event" | "ip";

const RISK_VIEW_TAB_KEY = "risk-view-tab";

function getInitialViewTab(): RiskViewTab {
  const stored = sessionStorage.getItem(RISK_VIEW_TAB_KEY);
  if (stored === "event" || stored === "ip") return stored;
  return "event";
}

const { RangePicker } = DatePicker;
const { Title, Paragraph } = Typography;

function formatTriggerRange(period: [Dayjs, Dayjs] | null) {
  if (!period?.[0] || !period[1]) {
    return { triggerStart: undefined, triggerEnd: undefined };
  }
  return {
    triggerStart: period[0].format("YYYY-MM-DD HH:mm:ss"),
    triggerEnd: period[1].format("YYYY-MM-DD HH:mm:ss"),
  };
}

const RiskTaskList = () => {
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState<RiskViewTab>(getInitialViewTab);
  const [searchInputs, setSearchInputs] = useState<RiskSearchForm>(EMPTY_SEARCH);
  const [filters, setFilters] = useState<RiskSearchForm>(EMPTY_SEARCH);
  const [eventSearchInputs, setEventSearchInputs] =
    useState<EventSearchForm>(EMPTY_EVENT_SEARCH);
  const [eventFilters, setEventFilters] =
    useState<EventSearchForm>(EMPTY_EVENT_SEARCH);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [listdata, setListdata] = useState<IpRiskListItem[]>([]);
  const [eventTopology, setEventTopology] =
    useState<LearnerNetworkTopologyJson | null>(null);
  const [eventLoading, setEventLoading] = useState(false);

  useEffect(() => {
    if (activeView !== "ip") return;
    void getListData();
  }, [page, filters, activeView]);

  useEffect(() => {
    if (activeView !== "event") return;
    void loadEventTopology();
  }, [eventFilters, activeView]);

  const loadEventTopology = async () => {
    setEventLoading(true);
    try {
      const range = formatTriggerRange(eventFilters.triggerPeriod);
      const data = await RiskService.getEventTopology({
        name: eventFilters.name || undefined,
        ...range,
      });
      setEventTopology(data);
    } catch (error) {
      console.error("获取事件拓扑失败", error);
      setEventTopology(null);
    } finally {
      setEventLoading(false);
    }
  };

  const getListData = async (opts?: { page?: number; nextFilters?: RiskSearchForm }) => {
    const curPage = opts?.page ?? page;
    const curFilters = opts?.nextFilters ?? filters;
    setLoading(true);
    try {
      const response = await RiskService.listRisks({
        limit: pageSize,
        offset: (curPage - 1) * pageSize,
        name: curFilters.name || undefined,
        subjectIp: curFilters.subjectIp || undefined,
      });
      setListdata(response.risks);
      setTotal(response.total);
    } catch (error) {
      console.error("获取风险列表失败", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDetailList = (id: number) => {
    navigate({
      pathname: "/risk/detail",
      search: `?id=${id}`,
    });
  };

  const handleIpDetail = (subjectIp: string) => {
    navigate({
      pathname: "/risk/ip-detail",
      search: `?ip=${encodeURIComponent(subjectIp)}`,
    });
  };

  const handleEventRiskClick = (riskId: number) => {
    handleDetailList(riskId);
  };

  const handleSearch = () => {
    setFilters({ ...searchInputs });
    setPage(1);
  };

  const handleReset = () => {
    setSearchInputs(EMPTY_SEARCH);
    setFilters(EMPTY_SEARCH);
    setPage(1);
  };

  const handleEventSearch = () => {
    setEventFilters({ ...eventSearchInputs });
  };

  const handleEventReset = () => {
    setEventSearchInputs(EMPTY_EVENT_SEARCH);
    setEventFilters(EMPTY_EVENT_SEARCH);
  };

  const handleViewChange = (key: string) => {
    const tab = key as RiskViewTab;
    setActiveView(tab);
    sessionStorage.setItem(RISK_VIEW_TAB_KEY, tab);
  };

  const updateSearchInput = (key: keyof RiskSearchForm, value: string) => {
    setSearchInputs((prev) => ({ ...prev, [key]: value }));
  };

  const columns: ColumnsType<IpRiskListItem> = [
    {
      title: "风险主体（IP）",
      dataIndex: "subjectIp",
      key: "subjectIp",
      width: 150,
      align: "center",
      render: (text: string) => (
        <TextWithTooltip text={text || ""} className="font-medium" />
      ),
    },
    {
      title: "风险数",
      dataIndex: "riskCount",
      key: "riskCount",
      width: 90,
      align: "center",
      render: (count: number) =>
        count > 0 ? (
          <span className="font-medium">{count}</span>
        ) : (
          <span className="text-[#8c8c8c]">-</span>
        ),
    },
    {
      title: "风险名称",
      dataIndex: "risks",
      key: "risks",
      width: 320,
      align: "center",
      render: (risks: IpRiskListItem["risks"]) =>
        risks?.length ? (
          <div className="flex flex-wrap justify-center gap-1 max-w-full">
            {risks.map((risk) => {
              const label = `${risk.name}（${risk.triggerCount}）`;
              return (
                <Tooltip key={risk.name} title={label}>
                  <Tag color="processing" className="!m-0 max-w-full truncate">
                    {label}
                  </Tag>
                </Tooltip>
              );
            })}
          </div>
        ) : (
          <span className="text-[#8c8c8c]">-</span>
        ),
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      fixed: "right",
      align: "center",
      render: (_: unknown, record: IpRiskListItem) => (
        <Tooltip title="查看详情">
          <Button
            variant="link"
            color="primary"
            onClick={() => handleIpDetail(record.subjectIp)}
          >
            详情
          </Button>
        </Tooltip>
      ),
    },
  ];

  return (
    <div className="task-list-page bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <div className="flex h-full min-h-0 flex-col gap-[12px]">
        <div className="rounded-[8px] bg-[#fff] px-[16px] pt-[8px] pb-0 shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
          <Tabs
            activeKey={activeView}
            onChange={handleViewChange}
            items={[
              { key: "event", label: "事件视角" },
              { key: "ip", label: "IP 视角" },
            ]}
          />
        </div>

        {activeView === "event" ? (
          <>
            <Card
              bordered={false}
              className="shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]"
              styles={{ body: { padding: "16px 16px 12px" } }}
            >
              <div className="risk-filter-row">
                <Input
                  className="risk-filter-field"
                  prefix="风险名称"
                  placeholder="请输入"
                  value={eventSearchInputs.name}
                  onChange={(e) =>
                    setEventSearchInputs((prev) => ({
                      ...prev,
                      name: e.target.value,
                    }))
                  }
                />
                <div className="risk-filter-range risk-filter-field">
                  <span className="risk-filter-range__prefix">触发时段</span>
                  <RangePicker
                    className="risk-filter-range__picker"
                    showTime
                    allowClear
                    format="YYYY-MM-DD HH:mm:ss"
                    placeholder={["开始时间", "结束时间"]}
                    value={eventSearchInputs.triggerPeriod}
                    onChange={(value) =>
                      setEventSearchInputs((prev) => ({
                        ...prev,
                        triggerPeriod: value as [Dayjs, Dayjs] | null,
                      }))
                    }
                  />
                </div>
              </div>
              <div className="mt-3 flex justify-end">
                <Space>
                  <Button onClick={handleEventReset}>重置</Button>
                  <Button type="primary" onClick={handleEventSearch}>
                    查询
                  </Button>
                </Space>
              </div>
            </Card>
            <Card
              bordered={false}
              className="min-h-0 flex-1 overflow-auto shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]"
              styles={{ body: { padding: 16 } }}
              loading={eventLoading}
            >
              <Title level={5} className="!mb-1 !mt-0">
                风险事件网络拓扑（IP / 端口）
              </Title>
              <Paragraph type="secondary" className="!mb-4 text-xs">
                默认展示全部风险事件；绿=良性、红=攻击。点击卡片右上角「详情」进入风险详情页。
              </Paragraph>
              <LearnerInternalTopologyPanel
                data={eventTopology}
                onRiskClick={handleEventRiskClick}
              />
            </Card>
          </>
        ) : (
          <>
            <div className="rounded-[8px] bg-[#fff] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <div className="risk-filter-row">
                <Input
                  className="risk-filter-field"
                  prefix="风险名称"
                  placeholder="请输入"
                  value={searchInputs.name}
                  onChange={(e) => updateSearchInput("name", e.target.value)}
                />
                <Input
                  className="risk-filter-field"
                  prefix="风险主体（IP）"
                  placeholder="请输入"
                  value={searchInputs.subjectIp}
                  onChange={(e) => updateSearchInput("subjectIp", e.target.value)}
                />
              </div>
              <div className="mt-3 flex justify-end">
                <Space>
                  <Button onClick={handleReset}>重置</Button>
                  <Button type="primary" onClick={handleSearch}>
                    查询
                  </Button>
                </Space>
              </div>
            </div>
            <div className="min-h-0 flex-1 rounded-[8px] bg-[#fff] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <Table
                className="w-full max-w-full min-w-0"
                columns={columns}
                dataSource={listdata}
                rowKey="id"
                size="middle"
                loading={loading}
                pagination={{
                  current: page,
                  pageSize: pageSize,
                  total: total,
                  showTotal: (t) => `共 ${t} 条`,
                  onChange: setPage,
                }}
                scroll={{ x: 710, y: "calc(100vh - 420px)" }}
                bordered
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default RiskTaskList;
