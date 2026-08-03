import { Stack, useRouter, useSegments } from "expo-router";
import * as Notifications from "expo-notifications";
import { useEffect, useState } from "react";
import { readSession } from "@/lib/session";
Notifications.setNotificationHandler({handleNotification:async()=>({shouldShowBanner:true,shouldShowList:true,shouldPlaySound:false,shouldSetBadge:false})});
export default function RootLayout(){const segments=useSegments();const router=useRouter();const [ready,setReady]=useState(false);useEffect(()=>{void readSession().then((session)=>{const publicRoute=segments[0]==="login";if(!session&&!publicRoute)router.replace("/login");if(session&&publicRoute)router.replace("/(tabs)");setReady(true)})},[segments,router]);if(!ready)return null;return <Stack screenOptions={{headerShown:false}}/>}
