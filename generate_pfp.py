from PIL import Image

def generate_whatsapp_profile_photo(logo_path: str, output_path: str = "WhatsApp_Profile_Photo.png", size: int = 500):
    img = Image.open(logo_path).convert("RGBA")
    square_img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    
    logo_width, logo_height = img.size
    target_width = int(size * 0.8)
    target_height = int((logo_height / logo_width) * target_width)
    
    if target_height > int(size * 0.8):
        target_height = int(size * 0.8)
        target_width = int((logo_width / logo_height) * target_height)
        
    resized_logo = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    paste_x = (size - target_width) // 2
    paste_y = (size - target_height) // 2
    
    square_img.paste(resized_logo, (paste_x, paste_y), resized_logo)
    final_output = square_img.convert("RGB")
    final_output.save(output_path, "PNG", quality=95)
    return output_path

generate_whatsapp_profile_photo("GlobalStar_Logo.png", "WhatsApp_Profile_Photo.png")
print("Profile photo created successfully!")