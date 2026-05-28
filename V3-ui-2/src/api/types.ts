/** 任务步骤状态（与 react-ui 一致） */
export enum Status {
  IDLE = 1,
  RUNNING = 2,
  COMPLETED = 3,
  FAILED = 4,
  CANCELLING = 5,
  CANCELLED = 6,
}

export interface Categories {
  id: number;
  name: string;
  originalName: string;
  description: string;
  grading?: string;
  children: Categories[];
  fields: { id: number; similarity: number }[];
}

export interface StepStatusItem {
  status: Status;
  message?: string;
}

export interface ImportStepStatus {
  importStatus: StepStatusItem;
}

export interface LabelStepStatus {
  similarityStatus?: StepStatusItem;
  garbledStatus?: StepStatusItem;
  generatedDescriptionStatus?: StepStatusItem;
  llmInferenceStatus?: StepStatusItem;
}

export interface TrainingStepStatus {
  classifierTraining?: StepStatusItem;
  classifierPrediction?: StepStatusItem;
  graderTraining?: StepStatusItem;
  graderPrediction?: StepStatusItem;
}

export interface PredictionStepStatus {
  classifierPrediction?: StepStatusItem;
  graderPrediction?: StepStatusItem;
}

export interface LlmInferenceStatus {
  classification?: StepStatusItem;
  grading?: StepStatusItem;
  dataLabel?: StepStatusItem;
  description?: StepStatusItem;
}

/** 风险事件（单条触发记录） */
export interface RiskItem {
  id: number;
  /** 风险主体 IP */
  subjectIp: string;
  /** 风险名称 */
  name: string;
  /** 触发时间（展示用） */
  triggerTime: string;
  /** 风险说明 */
  description: string;
  /** 风险特征 */
  features: string;
}

/** IP 视角列表：单个风险名称及触发次数 */
export interface IpRiskNameStat {
  name: string;
  /** 后端学习器名；同一风险名称可能来自多个学习器 */
  learnerName?: string;
  triggerCount: number;
}

/** IP 视角列表行（一行一个 IP，含多个风险名称） */
export interface IpRiskListItem {
  id: number;
  subjectIp: string;
  /** 该 IP 关联的学习器数量 */
  riskCount: number;
  risks: IpRiskNameStat[];
}

/** 风险任务列表行（结构对齐 react-ui Task） */
export interface Task {
  id: number;
  name: string;
  description: string;
  dataFileName: string;
  categories: Categories[];
  createdAt: Date;
  creator: { id: number; username: string } | null;
  importStepStatus: ImportStepStatus;
  labelStepStatus?: LabelStepStatus;
  llmInferenceStatus?: LlmInferenceStatus;
  trainingStepStatus?: TrainingStepStatus;
  predictionStepStatus?: PredictionStepStatus;
  lastStep?: number;
  /** 列表展示用格式化时间 */
  time?: string;
}
