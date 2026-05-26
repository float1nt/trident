import { Button, Form, Input, Space } from "antd";
import { MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import type { FormListFieldData } from "antd/es/form";

const IPV4_REGEX =
  /^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)$/;

export interface IpRangeItem {
  startIp: string;
  endIp: string;
}

export const EMPTY_IP_RANGE: IpRangeItem = { startIp: "", endIp: "" };

export function isValidIpv4(value: string): boolean {
  return IPV4_REGEX.test(value.trim());
}

interface IpRangeFormListProps {
  /** Form.List 字段名，如 sourceIpRanges */
  name: string | (string | number)[];
}

function IpRangeRow({
  field,
  remove,
  canRemove,
}: {
  field: FormListFieldData;
  remove: (index: number) => void;
  canRemove: boolean;
}) {
  return (
    <Space align="start" className="mb-2 flex w-full">
      <Form.Item
        {...field}
        name={[field.name, "startIp"]}
        rules={[
          { required: true, message: "请输入起始 IP" },
          {
            validator: async (_, value) => {
              if (!value || isValidIpv4(value)) return;
              throw new Error("请输入合法的 IPv4 地址");
            },
          },
        ]}
        className="mb-0 flex-1"
        label="起始 IP"
        colon={false}
      >
        <Input placeholder="例如 10.0.0.0" allowClear />
      </Form.Item>
      <span className="mt-[34px] text-[#bfbfbf]">—</span>
      <Form.Item
        {...field}
        name={[field.name, "endIp"]}
        rules={[
          { required: true, message: "请输入结束 IP" },
          {
            validator: async (_, value) => {
              if (!value || isValidIpv4(value)) return;
              throw new Error("请输入合法的 IPv4 地址");
            },
          },
        ]}
        className="mb-0 flex-1"
        label="结束 IP"
        colon={false}
      >
        <Input placeholder="例如 10.255.255.255" allowClear />
      </Form.Item>
      {canRemove ? (
        <MinusCircleOutlined
          className="mt-[34px] cursor-pointer text-base text-[#ff4d4f]"
          onClick={() => remove(field.name)}
          aria-label="删除该 IP 范围"
        />
      ) : (
        <span className="mt-[34px] inline-block w-4" aria-hidden />
      )}
    </Space>
  );
}

/** 采集 IP 范围：起始 IP — 结束 IP，支持多行增删 */
export default function IpRangeFormList({ name }: IpRangeFormListProps) {
  return (
    <Form.List
      name={name}
      rules={[
        {
          validator: async (_, ranges: IpRangeItem[] | undefined) => {
            if (!ranges || ranges.length < 1) {
              throw new Error("请至少添加一条 IP 范围");
            }
          },
        },
      ]}
    >
      {(fields, { add, remove }, { errors }) => (
        <div className="w-full max-w-[720px]">
          {fields.map((field) => (
            <IpRangeRow
              key={field.key}
              field={field}
              remove={remove}
              canRemove={fields.length > 1}
            />
          ))}
          <Form.Item className="mb-0">
            <Button
              type="dashed"
              onClick={() => add({ ...EMPTY_IP_RANGE })}
              icon={<PlusOutlined />}
              className="w-full max-w-[360px]"
            >
              添加 IP 范围
            </Button>
            <Form.ErrorList errors={errors} />
          </Form.Item>
        </div>
      )}
    </Form.List>
  );
}
