import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: "https://gridrudder.com", lastModified: new Date(), changeFrequency: "weekly", priority: 1 },
    { url: "https://gridrudder.com/privacy", lastModified: new Date(), changeFrequency: "monthly", priority: 0.3 },
  ];
}
