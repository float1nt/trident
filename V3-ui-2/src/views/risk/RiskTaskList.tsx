import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Table, Input, Button, Space, Tooltip, Tag, Tabs, DatePicker } from "antd";
import type { Dayjs } from "dayjs";
import { EyeOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { RiskItem } from "@/api/types";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import { fetchMockRiskList } from "@/mock/riskTasks";
import "./RiskTaskList.css";

type RiskSearchForm = {
  name: string;
  subjectIp: string;
  triggerTime: string;
};

const EMPTY_SEARCH: RiskSearchForm = {
  name: "",
  subjectIp: "",
  triggerTime: "",
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

const { RangePicker } = DatePicker;

const RiskTaskList = () => {
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState<RiskViewTab>("ip");
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
  const [listdata, setListdata] = useState<RiskItem[]>([]);

  useEffect(() => {
    if (activeView !== "ip") return;
    void getListData();
  }, [page, filters, activeView]);

  useEffect(() => {
    if (activeView !== "event") return;
    // 事件列表接入后在此根据 eventFilters 拉取数据
    void eventFilters;
  }, [activeView, eventFilters]);

  const getListData = async (opts?: { page?: number; nextFilters?: RiskSearchForm }) => {
    const curPage = opts?.page ?? page;
    const curFilters = opts?.nextFilters ?? filters;
    setLoading(true);
    try {
      const response = await fetchMockRiskList({
        limit: pageSize,
        offset: (curPage - 1) * pageSize,
        name: curFilters.name,
        subjectIp: curFilters.subjectIp,
        triggerTime: curFilters.triggerTime,
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

  const updateSearchInput = (key: keyof RiskSearchForm, value: string) => {
    setSearchInputs((prev) => ({ ...prev, [key]: value }));
  };

  const columns: ColumnsType<RiskItem> = [
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
      title: "风险名称",
      dataIndex: "name",
      key: "name",
      width: 180,
      align: "center",
      render: (text: string) =>
        text ? (
          <div className="flex justify-center max-w-full">
            <Tooltip title={text}>
              <Tag color="processing" className="!m-0 max-w-full truncate">
                {text}
              </Tag>
            </Tooltip>
          </div>
        ) : (
          <span className="text-[#8c8c8c]">-</span>
        ),
    },
    {
      title: "触发时间",
      dataIndex: "triggerTime",
      key: "triggerTime",
      width: 170,
      align: "center",
    },
    {
      title: "风险说明",
      dataIndex: "description",
      key: "description",
      width: 280,
      align: "center",
      render: (text: string) => (
        <TextWithTooltip
          text={text || ""}
          emptyText="-"
          className="text-gray-600"
        />
      ),
    },
    {
      title: "风险特征",
      dataIndex: "features",
      key: "features",
      width: 220,
      align: "center",
      render: (text: string) => (
        <TextWithTooltip text={text || ""} emptyText="-" />
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      fixed: "right",
      align: "center",
      render: (_: unknown, record: RiskItem) => (
        <Tooltip title="查看详情">
          <Button
            variant="link"
            color="primary"
            icon={<EyeOutlined />}
            onClick={() => handleDetailList(record.id)}
          />
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
            onChange={(key) => setActiveView(key as RiskViewTab)}
            items={[
              { key: "event", label: "事件视角" },
              { key: "ip", label: "IP 视角" },
            ]}
          />
        </div>

        {activeView === "event" ? (
          <>
            <div className="rounded-[8px] bg-[#fff] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
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
            </div>
            <div className="flex min-h-[320px] flex-1 items-center justify-center rounded-[8px] bg-[#fff] p-[16px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <span className="text-sm text-[#8c8c8c]">（占位）</span>
            </div>
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
                <Input
                  className="risk-filter-field"
                  prefix="触发时间"
                  placeholder="请输入"
                  value={searchInputs.triggerTime}
                  onChange={(e) => updateSearchInput("triggerTime", e.target.value)}
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
                scroll={{ x: 1100, y: "calc(100vh - 420px)" }}
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
