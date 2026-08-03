import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { enqueue } from "@/lib/offline";

type Detail = {
  id: string;
  title: string;
  description: string;
  price: number;
  district: string;
  area_m2: number;
  bedrooms: number;
  has_3d: boolean;
};

export default function Property() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const [item, setItem] = useState<Detail | null>(null);
  const [valuation, setValuation] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (slug) void api<Detail>(`/properties/${slug}`).then(setItem);
  }, [slug]);

  if (!item) {
    return (
      <Screen title="Đang tải…">
        <Text>Đang lấy dữ liệu</Text>
      </Screen>
    );
  }

  const property = item;

  async function save() {
    await enqueue("favorite.add", { property_id: property.id });
  }

  async function value() {
    setValuation(
      await api<Record<string, unknown>>("/valuations", {
        method: "POST",
        body: JSON.stringify({ property_id: property.id }),
      }),
    );
  }

  return (
    <Screen title={property.title}>
      <Text>
        {property.district} · {property.area_m2} m² · {property.bedrooms} phòng ngủ
      </Text>
      <Text>{new Intl.NumberFormat("vi-VN").format(property.price)} ₫</Text>
      <Text>{property.description}</Text>
      <Pressable onPress={() => void save()}>
        <Text>Lưu ngoại tuyến</Text>
      </Pressable>
      <Pressable onPress={() => void value()}>
        <Text>Ước tính giá AI</Text>
      </Pressable>
      {valuation && (
        <View>
          <Text>{JSON.stringify(valuation, null, 2)}</Text>
        </View>
      )}
      <Text>
        {property.has_3d
          ? "Tour 3D/AR/VR có thể mở từ web hoặc deep link."
          : "Chưa có mô hình 3D."}
      </Text>
    </Screen>
  );
}
