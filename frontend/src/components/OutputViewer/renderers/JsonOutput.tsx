import { JsonViewer } from "../../JsonViewer";

interface Props {
  data: any;
}

export function JsonOutput({ data }: Props) {
  return <JsonViewer data={data} maxHeight={400} />;
}
