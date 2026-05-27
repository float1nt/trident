import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Table, Input, Button, Space, Tooltip, Tag } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { RiskItem } from "@/api/types";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import { fetchMockRiskList } from "@/mock/riskTasks";
import "./RiskTaskList.css";

type RiskSearchForm = {
  name: string;
  subjectIp: string;
  description: string;
  triggerTime: string;
};

const EMPTY_SEARCH: RiskSearchForm = {
  name: "",
  subjectIp: "",
  description: "",
  triggerTime: "",
};

const RiskTaskList = () => {
  const navigate = useNavigate();
  const [searchInputs, setSearchInputs] = useState<RiskSearchForm>(EMPTY_SEARCH);
  const [filters, setFilters] = useState<RiskSearchForm>(EMPTY_SEARCH);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [listdata, setListdata] = useState<RiskItem[]>([]);

  useEffect(() => {
    void getListData();
  }, [page, filters]);

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
        description: curFilters.description,
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
      <div
        className="h-full w-full grid gap-[12px]"
        style={{ gridTemplateRows: "auto 1fr" }}
      >
        <div className="bg-[#fff] rounded-[8px] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
          <div className="grid grid-cols-3 gap-3 lg:grid-cols-4">
          <Input
            className="w-full"
            prefix="风险名称"
            placeholder="请输入"
            value={searchInputs.name}
            onChange={(e) => updateSearchInput("name", e.target.value)}
          />
          <Input
            className="w-full"
            prefix="风险主体（IP）"
            placeholder="请输入"
            value={searchInputs.subjectIp}
            onChange={(e) => updateSearchInput("subjectIp", e.target.value)}
          />
          <Input
            className="w-full"
            prefix="触发时间"
            placeholder="请输入"
            value={searchInputs.triggerTime}
            onChange={(e) => updateSearchInput("triggerTime", e.target.value)}
          />
          <Input
            className="w-full"
            prefix="风险说明"
            placeholder="请输入"
            value={searchInputs.description}
            onChange={(e) => updateSearchInput("description", e.target.value)}
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
        <div className="bg-[#fff] rounded-[8px] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)] w-full">
          <div style={{ width: "100%", display: "grid", gridRowGap: "16px" }}>
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
        </div>
      </div>
    </div>
  );
};

export default RiskTaskList;
