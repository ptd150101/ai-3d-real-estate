import { useEffect, useState } from "react";
import { router } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { registerPush } from "@/lib/notifications";
import { clearSession } from "@/lib/session";
import type { Bootstrap, Organization } from "@/lib/types";
export default function Settings(){const[orgs,setOrgs]=useState<Organization[]>([]);const[message,setMessage]=useState("");useEffect(()=>{void api<Bootstrap>("/mobile/bootstrap").then(x=>setOrgs(x.organizations))},[]);return <Screen title="Cài đặt"><Text>Tổ chức của bạn</Text>{orgs.map(o=><View key={o.id}><Text>{o.name} · {o.role}</Text></View>)}<Pressable onPress={()=>void registerPush().then(x=>setMessage(x?"Đã đăng ký push":"Push cần EAS project/device thật"))}><Text>Bật thông báo đẩy</Text></Pressable>{message&&<Text>{message}</Text>}<Pressable onPress={()=>void clearSession().then(()=>router.replace("/login"))}><Text>Đăng xuất</Text></Pressable></Screen>}
