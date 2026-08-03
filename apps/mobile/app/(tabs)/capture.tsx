import { useEffect, useMemo, useState } from "react";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system/legacy";
import {
  ActivityIndicator,
  Alert,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Screen } from "@/components/Screen";
import { api, upload } from "@/lib/api";
import type { Bootstrap, Organization, PropertyItem } from "@/lib/types";

type CaptureAsset = {
  uri: string;
  name: string;
  type: string;
  size: number;
  width: number;
  height: number;
};

type CaptureSessionResponse = { id: string; status: string };
type UploadResponse = { id: string; sha256: string; size_bytes: number; sequence?: number };
type ReconstructionResponse = {
  id: string;
  status: string;
  stage: string;
  representation?: string;
  progress?: number;
  artifact_id?: string | null;
  error?: string | null;
};

const MIN_IMAGES = 12;
const MAX_IMAGES = 60;
const MAX_IMAGE_BYTES = 25 * 1024 * 1024;

function wait(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function normalizeAssets(assets: ImagePicker.ImagePickerAsset[]): Promise<CaptureAsset[]> {
  const normalized: CaptureAsset[] = [];
  for (const [index, asset] of assets.entries()) {
    const info = await FileSystem.getInfoAsync(asset.uri);
    if (!info.exists || !info.size || info.size > MAX_IMAGE_BYTES) continue;
    normalized.push({
      uri: asset.uri,
      name: asset.fileName || `capture-${Date.now()}-${index + 1}.jpg`,
      type: asset.mimeType || "image/jpeg",
      size: info.size,
      width: asset.width,
      height: asset.height,
    });
  }
  return normalized;
}

export default function Capture() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [organizationId, setOrganizationId] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [representation, setRepresentation] = useState<"glb" | "gaussian_splat">("glb");
  const [captures, setCaptures] = useState<CaptureAsset[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploaded, setUploaded] = useState(0);
  const [job, setJob] = useState<ReconstructionResponse | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void api<Bootstrap>("/mobile/bootstrap")
      .then((data) => {
        setBootstrap(data);
        const organization = data.organizations[0];
        if (organization) setOrganizationId(organization.id);
      })
      .catch((error: unknown) => setMessage(String(error)));
  }, []);

  const organizations = bootstrap?.organizations ?? [];
  const properties = useMemo(
    () =>
      (bootstrap?.properties ?? []).filter(
        (property) => !organizationId || property.organization_id === organizationId,
      ),
    [bootstrap?.properties, organizationId],
  );

  useEffect(() => {
    if (!properties.some((property) => property.id === propertyId)) {
      setPropertyId(properties[0]?.id || "");
    }
  }, [properties, propertyId]);

  function addAssets(items: CaptureAsset[]) {
    const byUri = new Map(captures.map((item) => [item.uri, item]));
    for (const item of items) byUri.set(item.uri, item);
    const next = Array.from(byUri.values()).slice(0, MAX_IMAGES);
    setCaptures(next);
    if (next.length >= MAX_IMAGES) Alert.alert("Đã đủ ảnh", `Tối đa ${MAX_IMAGES} ảnh mỗi phiên.`);
  }

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) return Alert.alert("Cần quyền camera");
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.9,
      exif: false,
      allowsEditing: false,
    });
    if (result.canceled) return;
    const items = await normalizeAssets(result.assets);
    if (!items.length) return Alert.alert("Ảnh không hợp lệ", "Mỗi ảnh phải nhỏ hơn 25 MB.");
    addAssets(items);
  }

  async function choosePhotos() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) return Alert.alert("Cần quyền thư viện ảnh");
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 1,
      allowsMultipleSelection: true,
      selectionLimit: MAX_IMAGES,
    });
    if (result.canceled) return;
    const items = await normalizeAssets(result.assets);
    if (!items.length) return Alert.alert("Không có ảnh hợp lệ", "Mỗi ảnh phải nhỏ hơn 25 MB.");
    addAssets(items);
  }

  async function pollJob(jobId: string, headers: Record<string, string>) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await api<ReconstructionResponse>(`/reconstruction-jobs/${jobId}`, {
        headers,
      });
      setJob(current);
      if (["completed", "review", "failed", "rejected"].includes(current.status)) return current;
      await wait(3000);
    }
    throw new Error("Tái dựng vẫn đang chạy. Có thể kiểm tra tiếp trên trang quản trị.");
  }

  async function submit() {
    if (!organizationId || !propertyId) return Alert.alert("Chưa chọn đơn vị hoặc bất động sản");
    if (captures.length < MIN_IMAGES) {
      return Alert.alert("Chưa đủ ảnh", `Cần ít nhất ${MIN_IMAGES} ảnh có chồng lấn 60–80%.`);
    }
    setBusy(true);
    setUploaded(0);
    setJob(null);
    setMessage("Đang tạo phiên capture…");
    const headers = { "X-Organization-ID": organizationId };
    try {
      const session = await api<CaptureSessionResponse>("/captures", {
        method: "POST",
        headers,
        body: JSON.stringify({
          property_id: propertyId,
          capture_type: "images",
          requirements: {
            minimum_images: MIN_IMAGES,
            expected_images: captures.length,
            coverage: "360 degrees",
            overlap: "60-80%",
            source: "mobile",
          },
        }),
      });
      for (const [index, asset] of captures.entries()) {
        setMessage(`Đang tải ảnh ${index + 1}/${captures.length}…`);
        await upload<UploadResponse>(
          `/captures/${session.id}/upload`,
          { uri: asset.uri, name: asset.name, type: asset.type },
          {
            metadata: JSON.stringify({
              sequence: index + 1,
              width: asset.width,
              height: asset.height,
              size_bytes: asset.size,
              captured_from: "mobile",
              exposure_ok: true,
            }),
          },
          headers,
        );
        setUploaded(index + 1);
      }
      setMessage("Đã tải xong. Đang đưa vào hàng đợi GPU…");
      const queued = await api<ReconstructionResponse>(
        `/captures/${session.id}/reconstruct`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ representation }),
        },
      );
      setJob(queued);
      const completed = await pollJob(queued.id, headers);
      if (completed.status === "review") {
        setMessage("Tái dựng xong và đang chờ người phụ trách duyệt asset.");
      } else if (completed.status === "completed") {
        setMessage("Tái dựng và phát hành asset đã hoàn tất.");
      } else if (completed.status === "failed") {
        throw new Error(completed.error || "Tái dựng thất bại");
      } else {
        setMessage(`Phiên kết thúc với trạng thái ${completed.status}.`);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Capture 3D">
      <Text style={styles.guide}>
        Đi một vòng quanh phòng, giữ máy ngang, ánh sáng ổn định và chồng lấn 60–80% giữa hai
        ảnh liên tiếp. Cần ít nhất {MIN_IMAGES} ảnh.
      </Text>

      <Text style={styles.label}>Đơn vị</Text>
      <View style={styles.choices}>
        {organizations.map((organization: Organization) => (
          <Choice
            key={organization.id}
            active={organization.id === organizationId}
            label={organization.name}
            onPress={() => setOrganizationId(organization.id)}
          />
        ))}
      </View>

      <Text style={styles.label}>Bất động sản</Text>
      <View style={styles.choices}>
        {properties.map((property: PropertyItem) => (
          <Choice
            key={property.id}
            active={property.id === propertyId}
            label={`${property.title} · ${property.district}`}
            onPress={() => setPropertyId(property.id)}
          />
        ))}
      </View>

      <Text style={styles.label}>Đầu ra</Text>
      <View style={styles.row}>
        <Choice active={representation === "glb"} label="Mesh GLB" onPress={() => setRepresentation("glb")} />
        <Choice
          active={representation === "gaussian_splat"}
          label="Gaussian Splat"
          onPress={() => setRepresentation("gaussian_splat")}
        />
      </View>

      <View style={styles.row}>
        <Pressable style={styles.secondaryButton} onPress={() => void takePhoto()} disabled={busy}>
          <Text style={styles.secondaryText}>Chụp thêm ảnh</Text>
        </Pressable>
        <Pressable style={styles.secondaryButton} onPress={() => void choosePhotos()} disabled={busy}>
          <Text style={styles.secondaryText}>Chọn nhiều ảnh</Text>
        </Pressable>
      </View>

      <View style={styles.summary}>
        <Text style={styles.count}>{captures.length}/{MIN_IMAGES}+ ảnh</Text>
        <Text style={captures.length >= MIN_IMAGES ? styles.ready : styles.pending}>
          {captures.length >= MIN_IMAGES ? "Đủ điều kiện gửi" : `Còn thiếu ${MIN_IMAGES - captures.length} ảnh`}
        </Text>
      </View>

      <View style={styles.previewGrid}>
        {captures.slice(-6).map((asset, index) => (
          <Image key={`${asset.uri}-${index}`} source={{ uri: asset.uri }} style={styles.image} />
        ))}
      </View>

      {captures.length > 0 && !busy ? (
        <Pressable style={styles.clearButton} onPress={() => setCaptures([])}>
          <Text style={styles.clearText}>Xóa toàn bộ ảnh đã chọn</Text>
        </Pressable>
      ) : null}

      <Pressable
        style={[styles.primaryButton, (busy || captures.length < MIN_IMAGES) && styles.disabled]}
        onPress={() => void submit()}
        disabled={busy || captures.length < MIN_IMAGES}
      >
        {busy ? <ActivityIndicator color="white" /> : <Text style={styles.primaryText}>Tải lên và tái dựng</Text>}
      </Pressable>

      {busy || uploaded ? (
        <Text style={styles.progress}>Đã tải {uploaded}/{captures.length} ảnh</Text>
      ) : null}
      {job ? (
        <View style={styles.statusCard}>
          <Text style={styles.statusTitle}>Job {job.id.slice(0, 8)}</Text>
          <Text>Trạng thái: {job.status}</Text>
          <Text>Công đoạn: {job.stage}</Text>
          <Text>Tiến độ: {job.progress ?? 0}%</Text>
        </View>
      ) : null}
      {message ? <Text style={styles.message}>{message}</Text> : null}
    </Screen>
  );
}

function Choice({ active, label, onPress }: { active: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable style={[styles.choice, active && styles.choiceActive]} onPress={onPress}>
      <Text style={[styles.choiceText, active && styles.choiceTextActive]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  guide: { color: "#4b4a45", lineHeight: 21 },
  label: { fontWeight: "800", color: "#181714", marginTop: 4 },
  choices: { gap: 8 },
  row: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  choice: { borderWidth: 1, borderColor: "#cfc9ba", paddingVertical: 10, paddingHorizontal: 12, borderRadius: 12 },
  choiceActive: { backgroundColor: "#1d5f4a", borderColor: "#1d5f4a" },
  choiceText: { color: "#36352f", fontWeight: "600" },
  choiceTextActive: { color: "white" },
  secondaryButton: { flexGrow: 1, borderWidth: 1, borderColor: "#1d5f4a", padding: 14, borderRadius: 12 },
  secondaryText: { textAlign: "center", color: "#1d5f4a", fontWeight: "800" },
  primaryButton: { backgroundColor: "#1d5f4a", padding: 16, borderRadius: 12, minHeight: 52, justifyContent: "center" },
  primaryText: { color: "white", fontWeight: "800", textAlign: "center" },
  disabled: { opacity: 0.45 },
  summary: { backgroundColor: "white", padding: 16, borderRadius: 14, flexDirection: "row", justifyContent: "space-between" },
  count: { fontSize: 18, fontWeight: "800" },
  ready: { color: "#1d7a4c", fontWeight: "700" },
  pending: { color: "#a45b15", fontWeight: "700" },
  previewGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  image: { width: 96, height: 96, borderRadius: 12, backgroundColor: "#ddd" },
  clearButton: { padding: 8 },
  clearText: { color: "#9d2d2d", textAlign: "center", fontWeight: "700" },
  progress: { textAlign: "center", color: "#4b4a45" },
  statusCard: { backgroundColor: "white", padding: 16, borderRadius: 14, gap: 4 },
  statusTitle: { fontWeight: "800", marginBottom: 4 },
  message: { backgroundColor: "#fff8dd", color: "#4b3a10", padding: 12, borderRadius: 10 },
});
