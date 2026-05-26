import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Table,
  Input,
  Button,
  Space,
  Tooltip,
  Modal,
  Form,
  Tag,
} from "antd";
import {
  PlusOutlined,
  DeleteOutlined,
  EyeOutlined,
  EditOutlined,
  StopOutlined,
  ExportOutlined,
  FileTextOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Status, type Task } from "@/api/types";
import { message, messageBox } from "@/utils/message";
import { TextWithTooltip } from "@/components/TextWithTooltip";
import { StepTitle } from "@/components/StepTitle";
import { getCategoryDisplayName } from "@/utils/categories";
import {
  fetchMockTaskList,
  updateMockTask,
  deleteMockTask,
  batchDeleteMockTasks,
  stopMockTaskOperations,
} from "@/mock/riskTasks";
import "./RiskTaskList.css";

const { TextArea } = Input;

const RiskTaskList = () => {
  const navigate = useNavigate();
  const [inputValue, setInputValue] = useState("");
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [listdata, setListdata] = useState<Task[]>([]);
  const [newTaskModalOpen, setNewTaskModalOpen] = useState(false);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [form] = Form.useForm();
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [exportingTaskId, setExportingTaskId] = useState<number | null>(null);
  const [exportingCgTaskId, setExportingCgTaskId] = useState<number | null>(
    null
  );
  const exportBusy = exportingTaskId !== null || exportingCgTaskId !== null;

  useEffect(() => {
    void getListData();
    setSelectedRowKeys([]);
  }, [page]);

  const getListData = async (opts?: { name?: string; page?: number }) => {
    const curPage = opts?.page ?? page;
    const curName = (opts?.name ?? inputValue).trim();
    setLoading(true);
    try {
      const response = await fetchMockTaskList({
        limit: pageSize,
        offset: (curPage - 1) * pageSize,
        name: curName,
      });
      setListdata(response.tasks);
      setTotal(response.total);
    } catch (error) {
      console.error("获取任务列表失败", error);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = () => {
    setNewTaskModalOpen(true);
  };

  const handleNewTaskModalClose = () => {
    setNewTaskModalOpen(false);
  };

  const handleDetailList = (id: number) => {
    navigate({
      pathname: "/risk/detail",
      search: `?id=${id}`,
    });
  };

  const handleEdit = (task: Task) => {
    setEditingTask(task);
    form.setFieldsValue({
      name: task.name,
      description: task.description || "",
      dataFileName: task.dataFileName || "",
      classificationRootName: task.categories[0]?.name ?? "",
    });
    setEditModalVisible(true);
  };

  const handleEditCancel = () => {
    setEditModalVisible(false);
    setEditingTask(null);
    form.resetFields();
  };

  const handleEditSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (!editingTask) return;

      setLoading(true);
      updateMockTask(editingTask.id, {
        name: values.name.trim(),
        description: values.description?.trim() || "",
        dataFileName: values.dataFileName?.trim(),
        classificationRootName: values.classificationRootName?.trim(),
      });
      message.success("更新成功（Mock）");
      setEditModalVisible(false);
      setEditingTask(null);
      form.resetFields();
      await getListData();
      setLoading(false);
    } catch {
      // 表单验证失败
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const confirmed = await messageBox.confirm("确定删除该任务吗？", "提示");
      if (!confirmed) return;
      setLoading(true);
      deleteMockTask(id);
      message.success("删除成功（Mock）");
      await getListData();
      setLoading(false);
    } catch {
      // 用户取消
    }
  };

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning("请先选择要删除的任务");
      return;
    }

    try {
      const confirmed = await messageBox.confirm(
        `确定要删除选中的 ${selectedRowKeys.length} 个任务吗？`,
        "批量删除提示"
      );
      if (!confirmed) return;

      setLoading(true);
      const result = batchDeleteMockTasks(
        selectedRowKeys.map((key) =>
          typeof key === "number" ? key : Number(key)
        )
      );
      const { success, failed } = result;
      if (failed.length === 0) {
        message.success(`成功删除 ${success.length} 个任务（Mock）`);
      } else if (success.length > 0) {
        message.warning(
          `成功删除 ${success.length} 个，${failed.length} 个失败（Mock）`
        );
      } else {
        message.error("所有任务删除失败");
      }
      setSelectedRowKeys([]);
      await getListData();
      setLoading(false);
    } catch {
      // 用户取消
    }
  };

  const handleExport = async (record: Task) => {
    if (exportBusy) return;
    setExportingTaskId(record.id);
    try {
      await new Promise((r) => setTimeout(r, 600));
      message.success(`「${record.name}」预测结果导出成功（Mock）`);
    } finally {
      setExportingTaskId(null);
    }
  };

  const handleExportClassificationGrading = async (record: Task) => {
    if (exportBusy) return;
    setExportingCgTaskId(record.id);
    try {
      await new Promise((r) => setTimeout(r, 600));
      message.success(`「${record.name}」分类分级文件导出成功（Mock）`);
    } finally {
      setExportingCgTaskId(null);
    }
  };

  const handleStopOperations = async (
    id: number,
    options: { llm?: boolean; train?: boolean }
  ) => {
    try {
      const confirmed = await messageBox.confirm(
        "确定要停止该任务的所有运行操作吗？",
        "提示"
      );
      if (!confirmed) return;
      setLoading(true);
      stopMockTaskOperations(id);
      if (options.llm) {
        message.success("已提交停止请求，大模型任务将尽快停止（Mock）");
      }
      if (options.train) {
        message.success("已成功停止训练相关任务（Mock）");
      }
      await getListData();
      setLoading(false);
    } catch {
      // 用户取消
    }
  };

  const handleSearch = () => {
    setSelectedRowKeys([]);
    setPage(1);
    if (page === 1) void getListData({ name: inputValue.trim(), page: 1 });
  };

  const columns: ColumnsType<Task> = [
    {
      title: "任务名称",
      dataIndex: "name",
      key: "name",
      width: 100,
      align: "center",
      render: (text: string) => (
        <TextWithTooltip text={text || ""} className="font-medium" />
      ),
    },
    {
      title: "是否运行",
      dataIndex: "step",
      key: "step",
      width: 120,
      align: "center",
      render: (_: number, record: Task) => {
        const llmStatuses = [
          record.llmInferenceStatus?.classification?.status,
          record.llmInferenceStatus?.grading?.status,
          record.llmInferenceStatus?.dataLabel?.status,
          record.llmInferenceStatus?.description?.status,
        ];
        const trainStatuses = [
          record.trainingStepStatus?.classifierTraining?.status,
          record.trainingStepStatus?.classifierPrediction?.status,
          record.trainingStepStatus?.graderTraining?.status,
          record.trainingStepStatus?.graderPrediction?.status,
          record.predictionStepStatus?.classifierPrediction?.status,
          record.predictionStepStatus?.graderPrediction?.status,
        ];
        const isLlmRunning = llmStatuses.some((s) => s === Status.RUNNING);
        const isTrainRunning = trainStatuses.some((s) => s === Status.RUNNING);
        const isRunning = isLlmRunning || isTrainRunning;
        const handleStop = (e: React.MouseEvent) => {
          e.stopPropagation();
          void handleStopOperations(record.id, {
            llm: isLlmRunning,
            train: isTrainRunning,
          });
        };
        return (
          <Space>
            {isRunning ? (
              <>
                <Tag color="blue">运行中</Tag>
                <Tooltip title="停止所有运行操作">
                  <Button
                    type="text"
                    size="small"
                    icon={<StopOutlined />}
                    danger
                    onClick={handleStop}
                  />
                </Tooltip>
              </>
            ) : (
              <Tag color="default">无运行</Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
      width: 200,
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
      title: "数据源名称",
      dataIndex: "dataFileName",
      key: "dataFileName",
      width: 200,
      align: "center",
      render: (text: string) => <TextWithTooltip text={text || ""} />,
    },
    {
      title: "分类分级名称",
      dataIndex: "classificationName",
      key: "classificationName",
      width: 200,
      align: "center",
      render: (_: unknown, record: Task) => {
        if (!record.categories?.length) {
          return <TextWithTooltip text="" />;
        }
        return (
          <TextWithTooltip
            text={getCategoryDisplayName(record.categories[0]) || ""}
          />
        );
      },
    },
    {
      title: "上次步骤",
      key: "lastStepCol",
      width: 100,
      align: "center",
      render: (_: unknown, record: Task) => {
        const step = record.lastStep || 1;
        const getStepInfo = (s: number, task: Task) => {
          const stepNames: Record<number, string> = {
            1: "数据导入",
            2: "数据标注",
            3: "模型训练",
            4: "模型预测",
          };
          const stepName = stepNames[s] || `步骤${s}`;
          const tasks: Array<{
            id: string | number;
            status: Status;
            name?: string;
          }> = [];
          switch (s) {
            case 1:
              if (task.importStepStatus?.importStatus)
                tasks.push({
                  id: "import-1",
                  status: task.importStepStatus.importStatus.status,
                  name: "导入文件",
                });
              break;
            case 2:
              if (task.labelStepStatus?.garbledStatus)
                tasks.push({
                  id: "label-garbled",
                  status: task.labelStepStatus.garbledStatus.status,
                  name: "乱码检测",
                });
              if (task.labelStepStatus?.similarityStatus)
                tasks.push({
                  id: "label-similarity",
                  status: task.labelStepStatus.similarityStatus.status,
                  name: "相似度计算",
                });
              if (task.labelStepStatus?.llmInferenceStatus)
                tasks.push({
                  id: "label-llm",
                  status: task.labelStepStatus.llmInferenceStatus.status,
                  name: "大模型推理",
                });
              break;
            case 3:
              if (task.trainingStepStatus?.classifierTraining)
                tasks.push({
                  id: "train-cls",
                  status: task.trainingStepStatus.classifierTraining.status,
                  name: "训练分类模型",
                });
              if (task.trainingStepStatus?.classifierPrediction)
                tasks.push({
                  id: "train-cls-pred",
                  status: task.trainingStepStatus.classifierPrediction.status,
                  name: "分类检测",
                });
              break;
            case 4:
              if (task.predictionStepStatus?.classifierPrediction)
                tasks.push({
                  id: "pred-cls",
                  status: task.predictionStepStatus.classifierPrediction.status,
                  name: "分类预测",
                });
              if (task.predictionStepStatus?.graderPrediction)
                tasks.push({
                  id: "pred-grade",
                  status: task.predictionStepStatus.graderPrediction.status,
                  name: "分级预测",
                });
              break;
          }
          return { stepName, tasks };
        };

        const { stepName, tasks } = getStepInfo(step, record);
        return (
          <StepTitle
            title={stepName}
            tasks={tasks}
            showTitle={true}
            variant="table"
          />
        );
      },
    },
    {
      title: "导入时间",
      dataIndex: "time",
      key: "time",
      width: 180,
      align: "center",
    },
    {
      title: "创建者",
      dataIndex: "creator",
      key: "creator",
      width: 120,
      align: "center",
      render: (creator: { id: number; username: string } | null) => (
        <TextWithTooltip text={creator?.username || "-"} emptyText="-" />
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 230,
      fixed: "right",
      align: "center",
      render: (_: unknown, record: Task) => {
        const isImportSuccess =
          record.importStepStatus?.importStatus?.status === Status.COMPLETED;
        const actionDisabled = !isImportSuccess;
        const isThisRowPredictionExport = exportingTaskId === record.id;
        const isThisRowCgExport = exportingCgTaskId === record.id;
        return (
          <Space wrap>
            <Tooltip
              title={actionDisabled ? "文件导入未完成，无法操作" : "查看详情"}
            >
              <span>
                <Button
                  variant="link"
                  color="primary"
                  icon={<EyeOutlined />}
                  onClick={() => handleDetailList(record.id)}
                  disabled={actionDisabled}
                />
              </span>
            </Tooltip>
            <Tooltip
              title={actionDisabled ? "文件导入未完成，无法操作" : "编辑任务"}
            >
              <span>
                <Button
                  variant="link"
                  color="default"
                  icon={<EditOutlined />}
                  onClick={() => handleEdit(record)}
                  disabled={actionDisabled}
                />
              </span>
            </Tooltip>
            <Tooltip title="删除任务">
              <Button
                variant="link"
                color="danger"
                icon={<DeleteOutlined />}
                onClick={() => void handleDelete(record.id)}
              />
            </Tooltip>
            <Tooltip
              title={
                actionDisabled
                  ? "文件导入未完成，无法操作"
                  : isThisRowCgExport
                    ? "正在导出…"
                    : exportBusy && !isThisRowCgExport
                      ? "其他任务正在导出，请稍候"
                      : "导出分类分级文件"
              }
            >
              <span>
                <Button
                  variant="link"
                  color="default"
                  icon={<FileTextOutlined />}
                  onClick={() => void handleExportClassificationGrading(record)}
                  disabled={actionDisabled || exportBusy}
                  loading={isThisRowCgExport}
                />
              </span>
            </Tooltip>
            <Tooltip
              title={
                actionDisabled
                  ? "文件导入未完成，无法操作"
                  : isThisRowPredictionExport
                    ? "正在导出…"
                    : exportBusy && !isThisRowPredictionExport
                      ? "其他任务正在导出，请稍候"
                      : "导出数据"
              }
            >
              <span>
                <Button
                  variant="link"
                  color="default"
                  icon={<ExportOutlined />}
                  onClick={() => void handleExport(record)}
                  disabled={actionDisabled || exportBusy}
                  loading={isThisRowPredictionExport}
                />
              </span>
            </Tooltip>
          </Space>
        );
      },
    },
  ];

  const rowSelection = {
    selectedRowKeys,
    onChange: (selectedKeys: React.Key[]) => {
      setSelectedRowKeys(selectedKeys);
    },
  };

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
              prefix="任务名称"
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
                setSelectedRowKeys([]);
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
          <div className="flex flex-row justify-between items-center pb-[12px] w-full">
            {selectedRowKeys.length > 0 ? (
              <Button
                icon={<DeleteOutlined />}
                onClick={() => void handleBatchDelete()}
                loading={loading}
              >
                批量删除 ({selectedRowKeys.length})
              </Button>
            ) : (
              <Tooltip
                title="请至少选择1条数据"
                placement="bottomLeft"
                color="#fff"
                arrow={false}
              >
                <span>
                  <Button icon={<DeleteOutlined />} disabled>
                    批量删除
                  </Button>
                </span>
              </Tooltip>
            )}
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
              新建任务
            </Button>
          </div>
          <div style={{ width: "100%", display: "grid", gridRowGap: "16px" }}>
            <Table
              className="w-full max-w-full min-w-0"
              columns={columns}
              dataSource={listdata}
              rowKey="id"
              size="middle"
              rowSelection={rowSelection}
              loading={loading}
              pagination={{
                current: page,
                pageSize: pageSize,
                total: total,
                showTotal: (t) => `共 ${t} 条`,
                onChange: setPage,
              }}
              scroll={{ x: 1450, y: "calc(100vh - 364px)" }}
              bordered
            />
          </div>
        </div>
      </div>
      <Modal
        title="编辑任务"
        open={editModalVisible}
        onOk={() => void handleEditSubmit()}
        onCancel={handleEditCancel}
        confirmLoading={loading}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="任务名称"
            name="name"
            rules={[
              { required: true, message: "请输入任务名称" },
              { max: 63, message: "任务名称不能超过63个字符" },
            ]}
          >
            <Input placeholder="请输入任务名称" maxLength={63} showCount />
          </Form.Item>
          <Form.Item
            label="任务描述"
            name="description"
            rules={[{ max: 150, message: "任务描述不能超过150个字符" }]}
          >
            <TextArea
              placeholder="请输入任务描述"
              rows={4}
              maxLength={150}
              showCount
            />
          </Form.Item>
          <Form.Item
            label="数据源名称"
            name="dataFileName"
            rules={[{ max: 255, message: "数据源名称不能超过255个字符" }]}
          >
            <Input placeholder="请输入数据源名称" maxLength={255} showCount />
          </Form.Item>
          <Form.Item
            label="分类分级名称"
            name="classificationRootName"
            rules={[{ max: 100, message: "分类分级名称不能超过100个字符" }]}
          >
            <Input placeholder="请输入分类分级名称" maxLength={100} showCount />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="新建AI智能分类分级任务"
        open={newTaskModalOpen}
        onCancel={handleNewTaskModalClose}
        footer={[
          <Button key="close" onClick={handleNewTaskModalClose}>
            关闭
          </Button>,
        ]}
        width={480}
        centered
      >
        <p className="text-[#8c8c8c] text-sm py-4">
          新建任务功能开发中，当前为 Mock 列表演示。
        </p>
      </Modal>
    </div>
  );
};

export default RiskTaskList;
