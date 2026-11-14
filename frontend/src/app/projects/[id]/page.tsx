"use client";
import { useParams } from "next/navigation";
import { ProjectWorkspace } from "@/components/project/workspace";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  return <ProjectWorkspace id={id} />;
}
