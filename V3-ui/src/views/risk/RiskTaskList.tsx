import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Table, Input, Button, Space, Tooltip, Tag } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { RiskItem } from "@/api/types";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import { fetchMockRiskList } from "@/mock/riskTasks";
import "./RiskTaskList.css";

const RiskTaskList = () => {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState("");
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [listdata, setListdata] = useState<RiskItem[]>([]);

  useEffect(() => {
    void getListData();
  }, [page]);

  const getListData = async (opts?: { name?: string; page?: number }) => {
    const curPage = opts?.page ?? page;
    const curName = (opts?.name ?? inputValue).trim();
    setLoading(true);
    try {
      const response = await fetchMockRiskList({
        limit: pageSize,
        offset: (curPage - 1) * pageSize,
        name: curName,
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
    setPage(1);
    if (page === 1) void getListData({ name: inputValue.trim(), page: 1 });
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
        style={{ gridTemplateRows: "60px 1fr" }}
      >
        <div className="flex flex-row items-center bg-[#fff] rounded-[8px] p-[16px] pb-[12px] shadow-[0_2px_6px_0_rgba(28,41,90,0.04)]">
          <div className="basis-1/3 max-w-1/3">
            <Input
              className="w-full"
              prefix="风险名称"
              placeholder="请输入"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
            />
          </div>
          <Space className="basis-2/3 flex justify-end">
            <Button
              onClick={() => {
                const nextValue = "";
                setInputValue(nextValue);
                if (page === 1) void getListData({ name: nextValue, page: 1 });
                else setPage(1);
              }}
            >
              重置
            </Button>
            <Button type="primary" onClick={handleSearch}>
              查询
            </Button>
          </Space>
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
              scroll={{ x: 1100, y: "calc(100vh - 364px)" }}
              bordered
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default RiskTaskList;
