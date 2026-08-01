import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
type Thread={id:string;subject?:string;unread_count?:number};
export default function Agent(){const[threads,setThreads]=useState<Thread[]>([]);useEffect(()=>{void api<{items?:Thread[]} | Thread[]>("/messages/threads").then(x=>setThreads(Array.isArray(x)?x:x.items??[])).catch(()=>{})},[]);return <Screen title="Agent workspace"><Text>Hộp thư và lead được đồng bộ từ nền P1/P2.</Text>{threads.map(t=><View key={t.id}><Text>{t.subject??"Hội thoại"} · {t.unread_count??0} chưa đọc</Text></View>)}</Screen>}
