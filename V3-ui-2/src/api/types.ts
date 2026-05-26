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
