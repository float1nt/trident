import { useState, useEffect, useCallback } from "react";
import { useApi } from "@/hooks/useApi";
import { useEventTopologyPagination } from "@/hooks/useEventTopologyPagination";
import { useNavigate } from "react-router-dom";
import {
  Table,
  Input,
  Button,
  Space,
  Tag,
  DatePicker,
  Card,
  Spin,
  Typography,
  Pagination,
  Select,
} from "antd";
import PageTabs from "@/components/PageTabs";
import type { Dayjs } from "dayjs";
import type { ColumnsType } from "antd/es/table";
import type { IpRiskListItem } from "@/api/types";
import AppTooltip from "@/components/AppTooltip";
import OverflowTooltip from "@/components/OverflowTooltip";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import { LearnerInternalTopologyPanel } from "@/components/LearnerInternalTopologyPanel";
import {
  RiskService,
  type AttackTypeOption,
} from "@/api/services/RiskService";
import {
  createPaginationProps,
  createTablePagination,
  DEFAULT_EVENT_TOPOLOGY_PAGE_SIZE,
  DEFAULT_TABLE_PAGE_SIZE,
  EVENT_TOPOLOGY_PAGE_SIZE_OPTIONS,
} from "@/constants/tablePagination";
import { normalizeApiList } from "@/utils/normalizeApiList";
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
  attackTypes: string[];
  triggerPeriod: [Dayjs, Dayjs] | null;
};

const EMPTY_EVENT_SEARCH: EventSearchForm = {
  name: "",
  attackTypes: [],
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
const { Paragraph } = Typography;

function renderRiskTypeMaxTagPlaceholder(
  omittedValues: { label?: React.ReactNode; value?: string | number }[],
) {
  return (
    <AppTooltip
      title={
        <div className="flex max-w-[280px] flex-wrap gap-1">
          {omittedValues.map((item) => (
            <Tag key={String(item.value)} className="!m-0">
              {item.label}
            </Tag>
          ))}
        </div>
      }
    >
      <span>+{omittedValues.length}</span>
    </AppTooltip>
  );
}

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
  const [pageSize, setPageSize] = useState(DEFAULT_TABLE_PAGE_SIZE);
  const [eventPageSize, setEventPageSize] = useState(
    DEFAULT_EVENT_TOPOLOGY_PAGE_SIZE,
  );
  const { loading, run: runIpList } = useApi();
  const [listdata, setListdata] = useState<IpRiskListItem[]>([]);
  const [eventLoadError, setEventLoadError] = useState<string | null>(null);
  const [eventPage, setEventPage] = useState(1);
  const [attackTypeOptions, setAttackTypeOptions] = useState<AttackTypeOption[]>(
    [],
  );

  useEffect(() => {
    if (activeView !== "event") return;
    let cancelled = false;
    void RiskService.getAttackTypes({ scope: "event", includeCount: true })
      .then((items) => {
        if (!cancelled) setAttackTypeOptions(items);
      })
      .catch(() => {
        if (!cancelled) setAttackTypeOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [activeView]);

  const fetchEventTopologyPage = useCallback(
    async (offset: number, limit: number) => {
      const range = formatTriggerRange(eventFilters.triggerPeriod);
      return RiskService.getEventTopology({
        name: eventFilters.name || undefined,
        attackTypes:
          eventFilters.attackTypes.length > 0
            ? eventFilters.attackTypes
            : undefined,
        ...range,
        limit,
        offset,
      });
    },
    [eventFilters],
  );

  const {
    eventTopology,
    loading: eventTopologyLoading,
    total: eventTopologyListTotal,
    eventTopologyTypeTotal,
    eventTopologyRiskEventTotal,
  } = useEventTopologyPagination(
    activeView === "event",
    eventPage,
    eventPageSize,
    fetchEventTopologyPage,
  );

  const getListData = useCallback(
    async (opts?: { page?: number; nextFilters?: RiskSearchForm }) => {
      const curPage = opts?.page ?? page;
      const curFilters = opts?.nextFilters ?? filters;
      await runIpList(async () => {
        const response = await RiskService.listRisks({
          limit: pageSize,
          offset: (curPage - 1) * pageSize,
          name: curFilters.name || undefined,
          subjectIp: curFilters.subjectIp || undefined,
        });
        setListdata(normalizeApiList<IpRiskListItem>(response.risks));
        setTotal(response.total);
      });
    },
    [page, filters, pageSize, runIpList],
  );

  useEffect(() => {
    if (activeView !== "ip") return;
    void getListData();
  }, [page, filters, activeView, getListData]);

  useEffect(() => {
    if (activeView !== "event" || eventTopologyLoading) return;
    if (eventTopologyRiskEventTotal === 0 && eventFilters.triggerPeriod) {
      setEventLoadError(
        "当前触发时段内没有学习器，请点「重置」清空时段或扩大时间范围。",
      );
      return;
    }
    if (eventTopologyRiskEventTotal > 0) {
      setEventLoadError(null);
    }
  }, [
    activeView,
    eventTopologyLoading,
    eventTopologyRiskEventTotal,
    eventFilters.triggerPeriod,
  ]);

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
    setEventPage(1);
  };

  const handleEventReset = () => {
    setEventSearchInputs(EMPTY_EVENT_SEARCH);
    setEventFilters(EMPTY_EVENT_SEARCH);
    setEventLoadError(null);
    setEventPage(1);
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
      title: "风险主体",
      dataIndex: "subjectIp",
      key: "subjectIp",
      width: 150,
      render: (text: string) => (
        <TextWithTooltip text={text || ""} className="font-medium" />
      ),
    },
    {
      title: "风险数",
      dataIndex: "riskCount",
      key: "riskCount",
      width: 90,
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
      render: (risks: IpRiskListItem["risks"]) =>
        risks?.length ? (
          <div className="flex max-w-full flex-wrap justify-start gap-1">
            {risks.map((risk) => {
              const label = `${risk.name}（${risk.triggerCount}）`;
              return (
                <OverflowTooltip key={risk.name} title={label}>
                  <Tag color="processing" className="!m-0 max-w-full truncate">
                    {label}
                  </Tag>
                </OverflowTooltip>
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
      render: (_: unknown, record: IpRiskListItem) => (
        <Button
          variant="link"
          color="primary"
          onClick={() => handleIpDetail(record.subjectIp)}
        >
          查看详情
        </Button>
      ),
    },
  ];

  const pageLoading =
    activeView === "event"
      ? eventTopologyLoading && !eventTopology
      : loading;

  return (
    <div className="task-list-page bg-[#f6faff] p-[12px] h-full w-full rounded-[8px]">
      <Spin spinning={pageLoading} wrapperClassName="risk-page-spin">
        <div className="flex h-full min-h-0 flex-col gap-[12px]">
        <div className="rounded-[8px] bg-[#fff] px-[16px] py-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
          <PageTabs
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
                <div className="risk-filter-select risk-filter-field">
                  <span className="risk-filter-select__prefix">风险类型</span>
                  <Select
                    mode="multiple"
                    allowClear
                    showSearch
                    virtual={false}
                    listHeight={200}
                    optionFilterProp="label"
                    className="risk-filter-select__control"
                    classNames={{
                      popup: {
                        root: "app-scrollbar risk-filter-select-dropdown",
                      },
                    }}
                    placeholder="请选择"
                    maxTagCount="responsive"
                    maxTagPlaceholder={renderRiskTypeMaxTagPlaceholder}
                    value={eventSearchInputs.attackTypes}
                    options={attackTypeOptions.map((item) => ({
                      value: item.code,
                      label: item.name,
                      // item.count
                      //   ? `${item.name}（${item.count}）`
                      //   : item.name,
                      // title: item.desc,
                    }))}
                    onChange={(value) =>
                      setEventSearchInputs((prev) => ({
                        ...prev,
                        attackTypes: value,
                      }))
                    }
                  />
                </div>
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
                <div className="risk-filter-actions">
                  <Space>
                    <Button onClick={handleEventReset}>重置</Button>
                    <Button type="primary" onClick={handleEventSearch}>
                      查询
                    </Button>
                  </Space>
                </div>
              </div>
            </Card>
            <div className="h-[calc(100vh-250px)] flex-col rounded-[8px] bg-[#fff] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <div className="risk-event-summary-row">
                <div className="risk-event-summary">
                  <span className="risk-event-summary__bar" aria-hidden />
                  <p className="risk-event-summary__text">
                    总共
                    <span className="risk-event-summary__num">{eventTopologyTypeTotal}</span>
                    类风险
                    ，
                    <span className="risk-event-summary__num">
                      {eventTopologyRiskEventTotal}
                    </span>
                    个风险事件
                  </p>
                </div>
                {/* <Paragraph type="secondary" className="risk-event-summary__hint !mb-0">
                  <span style={{ color: CHART_GREEN ,fontSize: '18px'}}>→</span>
                  代表正常，
                  <span style={{ color: CHART_RED ,fontSize: '18px'}}>→</span>
                  代表异常。
                </Paragraph> */}
              </div>
              {eventLoadError ? (
                <Paragraph type="danger" className="!mb-3 text-xs">
                  {eventLoadError}
                </Paragraph>
              ) : null}
              <div className="risk-event-scroll">
                <LearnerInternalTopologyPanel
                  data={eventTopology}
                  onRiskClick={handleEventRiskClick}
                  emptyHint={eventLoadError ?? undefined}
                  loading={eventTopologyLoading && Boolean(eventTopology)}
                />
              </div>
              {eventTopologyListTotal > 0 ? (
                <div className="risk-event-pagination">
                  <Pagination
                    {...createPaginationProps({
                      current: eventPage,
                      pageSize: eventPageSize,
                      total: eventTopologyListTotal,
                      pageSizeOptions: EVENT_TOPOLOGY_PAGE_SIZE_OPTIONS.map(
                        String,
                      ),
                      onChange: (nextPage, nextPageSize) => {
                        if (nextPageSize !== eventPageSize) {
                          setEventPageSize(nextPageSize);
                          setEventPage(1);
                          return;
                        }
                        setEventPage(nextPage);
                      },
                    })}
                  />
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <>
            <div className="rounded-[8px] bg-[#fff] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <div className="risk-filter-row">
              <Input
                  className="risk-filter-field"
                  prefix="风险主体"
                  placeholder="请输入"
                  value={searchInputs.subjectIp}
                  onChange={(e) => updateSearchInput("subjectIp", e.target.value)}
                />
                <Input
                  className="risk-filter-field"
                  prefix="风险名称"
                  placeholder="请输入"
                  value={searchInputs.name}
                  onChange={(e) => updateSearchInput("name", e.target.value)}
                />
                <div className="risk-filter-actions">
                  <Space>
                    <Button onClick={handleReset}>重置</Button>
                    <Button type="primary" onClick={handleSearch}>
                      查询
                    </Button>
                  </Space>
                </div>
              </div>
            </div>
            <div className="min-h-0 flex-1 rounded-[8px] bg-[#fff] p-[16px]  shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
              <Table
                className="w-full max-w-full min-w-0"
                columns={columns}
                dataSource={listdata}
                rowKey="id"
                size="middle"
                pagination={createTablePagination({
                  current: page,
                  pageSize,
                  total,
                  onChange: (nextPage, nextPageSize) => {
                    setPage(nextPage);
                    setPageSize(nextPageSize);
                  },
                })}
                scroll={{ x: 710, y: "calc(100vh - 370px)" }}
                bordered
              />
            </div>
          </>
        )}
        </div>
      </Spin>
    </div>
  );
};

export default RiskTaskList;
