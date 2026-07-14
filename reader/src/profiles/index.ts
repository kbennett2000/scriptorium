// The profiles feature (DESIGN §14): first-run picker, per-device active profile, and the one-time
// migration of R2 dev-default data onto the chosen profile. No network here — the picker fetches the
// roster through the injected SyncClient.

export { ProfilePicker } from "./ProfilePicker";
export {
  readActiveProfile,
  writeActiveProfile,
  readUsersCache,
  writeUsersCache,
} from "./activeProfile";
export { migrateDefaultTo } from "./migrate";
