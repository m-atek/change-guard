require_relative "../lib/shop/pricing"

RSpec.describe "format price" do
  it "shows cents as euros with two decimals" do
    expect(Shop::Pricing.format_price(1250)).to eq("12.50")
  end
end
