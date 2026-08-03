import { useCallback, useState } from "react";
import { useFocusEffect } from "expo-router";
import { Pressable, Text } from "react-native";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { enqueue, flushQueue, queueSize } from "@/lib/offline";
type Favorite={property:{id:string;title:string;slug:string}};
export default function Favorites(){const[items,setItems]=useState<Favorite[]>([]);const[pending,setPending]=useState(0);const load=useCallback(()=>{void api<Favorite[]>("/favorites").then(setItems).catch(()=>{});void queueSize().then(setPending)},[]);useFocusEffect(useCallback(()=>{load();return()=>{}},[load]));async function remove(id:string){await enqueue("favorite.remove",{property_id:id});setItems(x=>x.filter(y=>y.property.id!==id));setPending(await queueSize())}return <Screen title="Bất động sản đã lưu"><Text>Đang chờ đồng bộ: {pending}</Text><Pressable onPress={()=>void flushQueue().then(load)}><Text>Đồng bộ ngay</Text></Pressable>{items.map(x=><Pressable key={x.property.id} onLongPress={()=>void remove(x.property.id)}><Text>{x.property.title}</Text></Pressable>)}</Screen>}
