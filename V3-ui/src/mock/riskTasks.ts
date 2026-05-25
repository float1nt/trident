import { Status, type Task } from "@/api/types";

const completedImport = {
  importStatus: { status: Status.COMPLETED, message: "导入完成" },
};

const runningLlm = {
  classification: { status: Status.RUNNING, message: "" },
  grading: { status: Status.IDLE, message: "" },
  dataLabel: { status: Status.IDLE, message: "" },
  description: { status: Status.IDLE, message: "" },
};

const idleLlm = {
  classification: { status: Status.IDLE, message: "" },
  grading: { status: Status.IDLE, message: "" },
  dataLabel: { status: Status.IDLE, message: "" },
  description: { status: Status.IDLE, message: "" },
};

/** 内存 mock 任务库（列表页读写） */
let mockTasks: Task[] = [
  {
    id: 1,
    name: "客户信息库分类分级",
    description: "对 CRM 客户主数据进行智能分类分级",
    dataFileName: "crm_customer_main.xlsx",
    categories: [
      {
        id: 101,
        name: "个人信息",
        originalName: "个人信息",
        description: "",
        grading: "3",
        children: [],
        fields: [],
      },
    ],
    createdAt: new Date("2026-05-20T10:30:00"),
    creator: { id: 1, username: "admin" },
    importStepStatus: completedImport,
    labelStepStatus: {
      garbledStatus: { status: Status.COMPLETED },
      similarityStatus: { status: Status.COMPLETED },
      llmInferenceStatus: { status: Status.RUNNING },
    },
    llmInferenceStatus: runningLlm,
    trainingStepStatus: {
      classifierTraining: { status: Status.IDLE },
      classifierPrediction: { status: Status.IDLE },
    },
    lastStep: 2,
  },
  {
    id: 2,
    name: "订单交易数据标注",
    description: "订单表字段自动标注与模型训练",
    dataFileName: "order_transaction_2025.csv",
    categories: [
      {
        id: 201,
        name: "交易数据",
        originalName: "交易数据",
        description: "",
        children: [],
        fields: [],
      },
    ],
    createdAt: new Date("2026-05-18T14:20:00"),
    creator: { id: 2, username: "zhangsan" },
    importStepStatus: completedImport,
    labelStepStatus: {
      garbledStatus: { status: Status.COMPLETED },
      similarityStatus: { status: Status.COMPLETED },
      llmInferenceStatus: { status: Status.COMPLETED },
    },
    llmInferenceStatus: idleLlm,
    trainingStepStatus: {
      classifierTraining: { status: Status.COMPLETED },
      classifierPrediction: { status: Status.RUNNING },
      graderTraining: { status: Status.IDLE },
    },
    lastStep: 3,
  },
  {
    id: 3,
    name: "日志审计字段预测",
    description: "安全审计日志字段分类预测任务",
    dataFileName: "audit_log_fields.xlsx",
    categories: [
      {
        id: 301,
        name: "日志信息",
        originalName: "日志信息",
        description: "",
        grading: "2",
        children: [],
        fields: [],
      },
    ],
    createdAt: new Date("2026-05-15T09:00:00"),
    creator: { id: 1, username: "admin" },
    importStepStatus: completedImport,
    labelStepStatus: {
      garbledStatus: { status: Status.COMPLETED },
      similarityStatus: { status: Status.COMPLETED },
      llmInferenceStatus: { status: Status.COMPLETED },
    },
    llmInferenceStatus: idleLlm,
    trainingStepStatus: {
      classifierTraining: { status: Status.COMPLETED },
      classifierPrediction: { status: Status.COMPLETED },
      graderTraining: { status: Status.COMPLETED },
      graderPrediction: { status: Status.COMPLETED },
    },
    predictionStepStatus: {
      classifierPrediction: { status: Status.COMPLETED },
      graderPrediction: { status: Status.COMPLETED },
    },
    lastStep: 4,
  },
  {
    id: 4,
    name: "人力资源表导入",
    description: "HR 系统人员表，导入中",
    dataFileName: "hr_employee.xlsx",
    categories: [],
    createdAt: new Date("2026-05-25T08:15:00"),
    creator: { id: 3, username: "lisi" },
    importStepStatus: {
      importStatus: { status: Status.RUNNING, message: "导入中" },
    },
    lastStep: 1,
  },
  {
    id: 5,
    name: "财务报表字段分级",
    description: "财务科目与字段智能分级",
    dataFileName: "finance_report_q1.xlsx",
    categories: [
      {
        id: 501,
        name: "财务数据",
        originalName: "财务数据",
        description: "",
        grading: "4",
        children: [],
        fields: [],
      },
    ],
    createdAt: new Date("2026-05-10T16:45:00"),
    creator: { id: 2, username: "zhangsan" },
    importStepStatus: completedImport,
    labelStepStatus: {
      garbledStatus: { status: Status.COMPLETED },
      similarityStatus: { status: Status.FAILED },
    },
    llmInferenceStatus: idleLlm,
    lastStep: 2,
  },
];

function formatTime(date: Date): string {
  return date.toLocaleString("zh-CN");
}

function withDisplayTime(tasks: Task[]): Task[] {
  return tasks.map((t) => ({
    ...t,
    time: formatTime(t.createdAt),
  }));
}

export interface MockTaskListParams {
  limit: number;
  offset: number;
  name?: string;
}

export interface MockTaskListResult {
  total: number;
  tasks: Task[];
}

/** 模拟分页查询 */
export function fetchMockTaskList(
  params: MockTaskListParams
): Promise<MockTaskListResult> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const keyword = (params.name ?? "").trim().toLowerCase();
      let filtered = mockTasks;
      if (keyword) {
        filtered = mockTasks.filter((t) =>
          t.name.toLowerCase().includes(keyword)
        );
      }
      const total = filtered.length;
      const slice = filtered.slice(
        params.offset,
        params.offset + params.limit
      );
      resolve({ total, tasks: withDisplayTime(slice) });
    }, 200);
  });
}

export function getMockTaskById(id: number): Task | undefined {
  return mockTasks.find((t) => t.id === id);
}

export function updateMockTask(
  id: number,
  patch: Partial<Pick<Task, "name" | "description" | "dataFileName">> & {
    classificationRootName?: string;
  }
): void {
  mockTasks = mockTasks.map((t) => {
    if (t.id !== id) return t;
    const next = { ...t, ...patch };
    if (patch.classificationRootName && t.categories.length > 0) {
      next.categories = [
        {
          ...t.categories[0],
          name: patch.classificationRootName,
          originalName: patch.classificationRootName,
        },
        ...t.categories.slice(1),
      ];
    }
    return next;
  });
}

export function deleteMockTask(id: number): void {
  mockTasks = mockTasks.filter((t) => t.id !== id);
}

export function batchDeleteMockTasks(ids: number[]): {
  success: number[];
  failed: number[];
} {
  const success: number[] = [];
  const failed: number[] = [];
  for (const id of ids) {
    if (mockTasks.some((t) => t.id === id)) {
      deleteMockTask(id);
      success.push(id);
    } else {
      failed.push(id);
    }
  }
  return { success, failed };
}

export function stopMockTaskOperations(id: number): void {
  mockTasks = mockTasks.map((t) => {
    if (t.id !== id) return t;
    const idle = { status: Status.IDLE, message: "" };
    return {
      ...t,
      llmInferenceStatus: t.llmInferenceStatus
        ? {
            classification: idle,
            grading: idle,
            dataLabel: idle,
            description: idle,
          }
        : t.llmInferenceStatus,
      trainingStepStatus: t.trainingStepStatus
        ? {
            classifierTraining: idle,
            classifierPrediction: idle,
            graderTraining: idle,
            graderPrediction: idle,
          }
        : t.trainingStepStatus,
    };
  });
}
