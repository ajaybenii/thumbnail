import streamlit as st
import folium
import asyncio
import pandas as pd
import csv
import os
import json
import tempfile
from PIL import Image
from polyline import decode
from pyppeteer import launch
from google.cloud import storage

# Streamlit page configuration
st.set_page_config(page_title="Polygon Map Generator", layout="wide")

# Title and description
st.title("Polygon Map Generator")
st.markdown("Upload a CSV file with city, sublocation, and polygon data to generate maps and upload them to GCS.")

# Initialize GCS client using environment variable
try:
    credentials_content = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_content:
        raise ValueError("GCP credentials not found in environment variable GOOGLE_APPLICATION_CREDENTIALS")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_credentials:
        temp_credentials.write(credentials_content.encode('utf-8'))
        temp_credentials.flush()
        client = storage.Client.from_service_account_json(temp_credentials.name)
    os.remove(temp_credentials_file.name)
    bucket_name = "static-site-data"
    bucket = client.get_bucket(bucket_name)
    st.success("Connected to Google Cloud Storage.")
except Exception as e:
    st.error(f"Failed to connect to GCS: {e}")
    st.stop()

# Display Chromium status
chromium_path = os.environ.get("PYPPETEER_EXECUTABLE_PATH", "/usr/bin/chromium-browser")
if os.path.exists(chromium_path):
    st.success(f"Chromium found at: {chromium_path}")
else:
    st.error(f"Chromium not found at: {chromium_path}. Ensure Chromium is installed.")
    # Debug alternative paths
    possible_paths = ["/usr/bin/chromium", "/usr/lib/chromium-browser/chromium-browser", "/usr/bin/chromium-browser"]
    for path in possible_paths:
        if os.path.exists(path):
            st.info(f"Found Chromium at alternative path: {path}")
            chromium_path = path
            break
    if not os.path.exists(chromium_path):
        st.warning("Cannot generate maps without Chromium.")
        st.stop()

# Async function to process coordinates and generate maps
async def process_coordinates(poly, sublocation, city, csv_writer):
    try:
        encoded_polyline = str(poly)
        if encoded_polyline != "0":
            decoded_coordinates = decode(encoded_polyline)

            # Create a bounding box for the polygon
            min_lat = min([coord[0] for coord in decoded_coordinates])
            max_lat = max([coord[0] for coord in decoded_coordinates])
            min_lon = min([coord[1] for coord in decoded_coordinates])
            max_lon = max([coord[1] for coord in decoded_coordinates])

            # Calculate the optimal zoom level to fit the polygon
            map_center = [(min_lat + max_lat) / 2, (min_lon + max_lon) / 2]
            map = folium.Map(location=map_center, zoom_start=13.4, tiles="OpenStreetMap", control_scale=True)
            map.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]], padding=(50, 50))

            # Create a polygon
            polygon = folium.Polygon(
                locations=decoded_coordinates,
                color='black',
                weight=12,
                fill=True,
                fill_color='#3AFFE6',
                fill_opacity=0.3,
            )
            polygon.add_to(map)

            # Add a large text label at the center
            folium.map.Marker(
                map_center,
                icon=folium.DivIcon(
                    html=f'<div style="font-size: 55px; font-weight: bold; color: black; -webkit-text-stroke: 0.5px white;">{sublocation}</div>',
                    icon_size=(300, 50),
                    icon_anchor=(150, 25)
                )
            ).add_to(map)

            # Save the map as HTML in a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as temp_html:
                map.save(temp_html.name)
                html_path = temp_html.name

            # Launch Pyppeteer with Chromium
            browser = await launch(
                headless=True,
                executablePath=chromium_path,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding'
                ],
                handleSIGINT=False,
                handleSIGTERM=False,
                handleSIGHUP=False
            )
            page = await browser.newPage()
            await page.setViewport({'width': 1200, 'height': 1200})

            # Add timeout and error handling
            try:
                await page.goto(f"file://{html_path}", waitUntil="networkidle2", timeout=30000)
                await asyncio.sleep(2)  # Wait for map to render
            except Exception as e:
                st.warning(f"Page load timeout for {sublocation}, trying alternative approach...")
                await page.goto(f"file://{html_path}", waitUntil="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)

            # Generate screenshot path
            localmap_path = f'{sublocation} {city}.png'
            local_map_path = local_map_path.replace(" ", "-").lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_png:
                screenshot_path = temp_png.name
                await page.screenshot({'path': screenshot_path, 'fullPage': True, 'quality': 100})

            # Clean up browser
            try:
                await browser.close()
            except Exception as e:
                st.warning(f"Browser cleanup warning for {sublocation}: {e}")

            # Upload to GCS
            gcs_map_path = f"localitymap-thumnail/{local_map_path}"
            blob = bucket.blob(gcs_map_path)
            blob.upload_from_filename(screenshot_path)

            # Generate public URL
            gcs_base_url = f"https://static.squareyards.com/{bucket_name}/"
            map_url = gcs_base_url + gcs_map_path
            map_url = map_url.replace("static-site-data/", "")

            # Write to CSV
            csv_writer.writerow([sublocation, city, local_map_path, map_url])

            # Clean up temporary files
            os.remove(html_path)
            os.remove(screenshot_path)

            return {"status": "success", "sublocation": sublocation, "city": city, "url": map_url}

    except Exception as e:
        st.error(f"Error processing {sublocation}, {city}: {e}")
        return {"status": "error", "sublocation": sublocation, "city": city, "error": str(e)}

# Async main function to process the CSV
async def main(df, output_csv_path):
    with open(output_csv_path, "w", newline="", encoding="utf-8") as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["SubLocation", "City", "Image File Name", "Image URL"])

        progress_bar = st.progress(0)
        status_text = st.empty()
        n = 1
        total_rows = len(df)

        for index, row in df.iterrows():
            # Adjust column names if your CSV uses different ones (e.g., HM_Polygon, Sublocationname)
            poly = row['Polygon']  # Change to 'HM_Polygon' if needed
            sublocation = row['SubLocationName']  # Change to 'Sublocationname' if needed
            city = row['CityName']  # Change to 'Cityname' if needed
            status_text.text(f"Processing {n}/{total_rows}: {sublocation}, {city}")
            result = await process_coordinates(poly, sublocation, city, csv_writer)
            progress_bar.progress(n / total_rows)
            n += 1

        status_text.text("Processing complete!")
        return output_csv_path

# File upload widget
uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

if uploaded_file:
    # Read the uploaded CSV
    try:
        df = pd.read_csv(uploaded_file)
        expected_columns = ['CityName', 'SubLocationName', 'Polygon']
        if not all(col in df.columns for col in expected_columns):
            st.error(f"CSV must contain columns: {', '.join(expected_columns)}")
        else:
            st.write("CSV uploaded successfully. Preview:")
            st.dataframe(df.head())

            # Only show Generate Maps button if Chromium is found
            if os.path.exists(chromium_path):
                # Button to start processing
                if st.button("Generate Maps"):
                    with st.spinner("Processing maps..."):
                        # Create a temporary file for the output CSV
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_csv:
                            output_csv_path = temp_csv.name

                        # Run the async main function
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            output_csv_path = loop.run_until_complete(main(df, output_csv_path))
                        except Exception as e:
                            st.error(f"Processing error: {e}")
                        finally:
                            try:
                                loop.close()
                            except:
                                pass

                        # Provide download link for the output CSV
                        with open(output_csv_path, "rb") as f:
                            st.download_button(
                                label="Download Output CSV",
                                data=f,
                                file_name="map_thumbnails_output.csv",
                                mime="text/csv"
                            )
                        os.remove(output_csv_path)
            else:
                st.warning("Cannot generate maps without Chromium. Ensure Chromium is installed.")

    except Exception as e:
        st.error(f"Error reading CSV: {e}")

# Footer
st.markdown("---")
st.markdown("Built with Streamlit and Folium. Ensure GCP credentials and Chromium are set up correctly.")