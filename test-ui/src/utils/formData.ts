/**
 * FormData 工具函数
 * 用于构建表单数据
 */

/**
 * 构建创建任务的 FormData
 * @param data 任务数据
 * @returns FormData 对象
 */
export function buildCreateTaskFormData(data: {
  name: string;
  description?: string;
  dataFile?: File | File[];
  ruleFile?: File;
  corpusFile?: File;
  dataFileSource?: "upload" | "reference";
  ruleFileSource?: "upload" | "reference";
  ruleFileFromShixi?: boolean;
  ruleFileBindGrading?: boolean;
  corpusFileSource?: "upload" | "reference";
  referenceDataTaskIds?: number[];
  referenceRuleTaskId?: number;
  referenceCorpusTaskId?: number;
}): FormData {
  const formData = new FormData();
  formData.append("name", data.name);
  if (data.description) {
    formData.append("description", data.description);
  }

  // 数据库文件处理
  if (data.dataFileSource === "reference") {
    // 引用模式：传递任务ID列表
    if (data.referenceDataTaskIds && data.referenceDataTaskIds.length > 0) {
      formData.append("dataFileSource", "reference");
      data.referenceDataTaskIds.forEach((taskId, index) => {
        formData.append(`referenceDataTaskIds[${index}]`, taskId.toString());
      });
    }
  } else {
    // 上传模式：传递文件（支持多个文件）
    if (data.dataFile) {
      formData.append("dataFileSource", "upload");
      if (Array.isArray(data.dataFile)) {
        // 多个文件
        data.dataFile.forEach((file) => {
          formData.append("dataFile", file);
        });
      } else {
        // 单个文件
        formData.append("dataFile", data.dataFile);
      }
    }
  }

  // 分类分级文件处理
  if (data.ruleFileSource === "reference") {
    // 引用模式：传递任务ID
    if (data.referenceRuleTaskId) {
      formData.append("ruleFileSource", "reference");
      formData.append("referenceRuleTaskId", data.referenceRuleTaskId.toString());
    }
  } else {
    // 上传模式：传递文件
    if (data.ruleFile) {
      formData.append("ruleFileSource", "upload");
      formData.append("ruleFile", data.ruleFile);
      if (data.ruleFileFromShixi) {
        formData.append("ruleFileFromShixi", "true");
      }
      // 分类绑定分级：默认关闭，仅显式开启时传 true
      formData.append(
        "ruleFileBindGrading",
        data.ruleFileBindGrading === true ? "true" : "false"
      );
    }
  }

  // 乱码推理语料文件处理
  if (data.corpusFileSource === "reference") {
    // 引用模式：传递任务ID
    if (data.referenceCorpusTaskId) {
      formData.append("corpusFileSource", "reference");
      formData.append("referenceCorpusTaskId", data.referenceCorpusTaskId.toString());
    }
  } else {
    // 上传模式：传递文件
    if (data.corpusFile) {
      formData.append("corpusFileSource", "upload");
      formData.append("corpusFile", data.corpusFile);
    }
  }

  return formData;
}

